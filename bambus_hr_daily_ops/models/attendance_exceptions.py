"""Saved HR decisions excuse specific missing intervals, never fabricate punches."""
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models


def merged(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def subtract(intervals, excluded):
    result = merged(intervals)
    for left, right in merged(excluded):
        result = [(a, b) for start, end in result for a, b in
                  ((start, min(end, left)), (max(start, right), end)) if b > a]
    return result


class ReviewedExceptionEmployee(models.Model):
    _inherit = 'hr.employee'

    def _attendance_session_intervals(self, day):
        self.ensure_one()
        day = fields.Date.to_date(day)
        contract = self._get_attendance_contract(day)
        calendar = contract.resource_calendar_id or self.resource_calendar_id
        tz = pytz.timezone(calendar.tz or self.env.user.tz or 'UTC')
        midnight = datetime.combine(day, time.min)
        def utc(hour):
            return tz.localize(midnight + timedelta(hours=hour)).astimezone(pytz.UTC).replace(tzinfo=None)
        return [(utc(start), utc(end)) for start, end in self._get_attendance_work_periods(day)]

    def _attendance_exception_context(self, day):
        """Only regular dates of effective Monthly/Daily contracts qualify."""
        self.ensure_one()
        day = fields.Date.to_date(day)
        template = self._get_attendance_automation_template(day)
        contract = self._get_attendance_contract(day)
        if (not contract or contract.company_id != self.company_id
                or contract.wage_type not in ('monthly', 'daily') or not template
                or template.reviewed_exception_day_pay != 'regularize'
                or self._is_attendance_weekly_off(day)):
            return False, [], self.env['hr.attendance'], []
        sessions = self._attendance_session_intervals(day)
        if not sessions:
            return False, [], self.env['hr.attendance'], []
        holidays = self.env['resource.calendar.leaves'].sudo().search_count([
            ('resource_id', '=', False), ('company_id', 'in', [False, self.company_id.id]),
            ('calendar_id', 'in', [False, contract.resource_calendar_id.id or self.resource_calendar_id.id]),
            ('date_from', '<', sessions[-1][1]), ('date_to', '>', sessions[0][0]),
        ])
        if holidays:
            return False, [], self.env['hr.attendance'], []
        calendar = contract.resource_calendar_id or self.resource_calendar_id
        tz = pytz.timezone(calendar.tz or self.env.user.tz or 'UTC')
        midnight = datetime.combine(day, time.min)
        local_start = tz.localize(midnight).astimezone(pytz.UTC).replace(tzinfo=None)
        local_end = tz.localize(midnight + timedelta(days=1)).astimezone(pytz.UTC).replace(tzinfo=None)
        atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', self.id), ('check_in', '>=', local_start), ('check_in', '<', local_end),
        ])
        # An open punch is ambiguous. HR must close/correct it before excusing time.
        if any(not att.check_out for att in atts):
            return False, [], atts, []
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id), ('state', 'not in', ['refuse', 'cancel']),
            ('date_from', '<', sessions[-1][1]), ('date_to', '>', sessions[0][0]),
        ])
        return template, sessions, atts, [(leave.date_from, leave.date_to) for leave in leaves]

    def _attendance_leave_half_sessions(self, day):
        """Use calendar Morning/Afternoon metadata, including split sessions."""
        day = fields.Date.to_date(day)
        contract = self._get_attendance_contract(day)
        calendar = contract.resource_calendar_id or self.resource_calendar_id
        week_type = str(self.env['resource.calendar.attendance'].get_week_type(day))
        rules = calendar.attendance_ids.filtered(lambda rule:
            not rule.display_type and rule.dayofweek == str(day.weekday())
            and (not rule.date_from or rule.date_from <= day)
            and (not rule.date_to or rule.date_to >= day)
            and (not calendar.two_weeks_calendar or rule.week_type == week_type))
        halves = {'am': [], 'pm': []}
        for hours, interval in zip(self._get_attendance_work_periods(day), self._attendance_session_intervals(day)):
            labels = set(rules.filtered(lambda rule: (rule.hour_from, rule.hour_to) == hours).mapped('day_period'))
            if labels == {'morning'}:
                halves['am'].append(interval)
            elif labels == {'afternoon'}:
                halves['pm'].append(interval)
        return halves

    def _attendance_exception_components(self, day):
        """Session-specific proposals and immutable coverage of each raw gap.

        A wholly absent session is never inferred to be a late/early exception.
        Grace changes fine minutes, but explicit review can excuse its raw gap.
        """
        template, sessions, atts, leave_intervals = self._attendance_exception_context(day)
        if not template:
            return None
        punches = merged((att.check_in, att.check_out) for att in atts if att.worked_hours > 0)
        half_sessions = self._attendance_leave_half_sessions(day)
        session_half = {interval: half for half, intervals in half_sessions.items() for interval in intervals}
        components = {}
        for index, (start, end) in enumerate(sessions):
            present = merged((max(start, a), min(end, b)) for a, b in punches if a < end and b > start)
            if not present:
                continue
            gaps = [('late', (start, present[0][0]), template.late_enabled,
                     template.late_grace_minutes if index == 0 else template.post_break_grace_minutes),
                    ('early', (present[-1][1], end), template.early_exit_enabled, template.early_exit_grace_minutes)]
            gaps += [('break', (left[1], right[0]), template.break_enabled, template.allowed_break_minutes)
                     for left, right in zip(present, present[1:])]
            for kind, interval, enabled, grace in gaps:
                coverage = subtract([interval], leave_intervals)
                minutes = sum((b - a).total_seconds() for a, b in coverage) / 60
                fine_minutes = max(0, int(minutes) - grace)
                if not enabled or fine_minutes <= 0:
                    continue
                key = '%s_%s' % (kind, session_half.get((start, end), 'am' if index == 0 else 'pm'))
                component = components.setdefault(key, {'hours': 0.0, 'coverage': []})
                component['hours'] += fine_minutes / 60
                component['coverage'] += [[fields.Datetime.to_string(a), fields.Datetime.to_string(b)] for a, b in coverage]
        return components

    def _get_attendance_day_pay_hours(self, day, worked_hours):
        actual = super()._get_attendance_day_pay_hours(day, worked_hours)
        template, sessions, atts, leave_intervals = self._attendance_exception_context(day)
        if not template or actual <= 0 or not atts:
            return actual
        sessions = [(start, end) for start, end in sessions if any(
            att.worked_hours > 0 and att.check_in < end and att.check_out > start for att in atts)]
        line = self.env['bambus.hr.attendance.sheet.line'].sudo().search([
            ('employee_id', '=', self.id), ('company_id', '=', self.company_id.id),
            ('date', '=', day), ('fine_state', 'in', ['approved', 'rejected']),
        ], order='id desc', limit=1)
        coverage = []
        for decision in (line.fine_review_data or {}).values():
            if decision.get('state') in ('approved', 'ignored'):
                coverage += [(fields.Datetime.to_datetime(a), fields.Datetime.to_datetime(b))
                             for a, b in decision.get('coverage', [])]
        # Credit only still-missing scheduled time, once, excluding any leave.
        covered = [(max(a, start), min(b, end)) for a, b in coverage for start, end in sessions
                   if a < end and b > start]
        excluded = leave_intervals + [(att.check_in, att.check_out) for att in atts]
        hours = sum((b - a).total_seconds() for a, b in subtract(covered, excluded)) / 3600
        return actual + hours
