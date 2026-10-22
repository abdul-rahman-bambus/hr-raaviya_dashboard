"""Normal attendance-day pay and separately approved missing-time fines."""
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models


def _merge(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def _subtract(intervals, exclusions):
    result = _merge(intervals)
    for left, right in _merge(exclusions):
        result = [(a, b) for start, end in result for a, b in
                  ((start, min(end, left)), (max(start, right), end)) if b > a]
    return result


class PartialAttendanceEmployee(models.Model):
    _inherit = 'hr.employee'

    def _fine_only_attendance_context(self, day):
        self.ensure_one()
        day = fields.Date.to_date(day)
        template = self._get_attendance_automation_template(day)
        if not template or template.partial_attendance_salary_treatment != 'fine_only':
            return None
        contract = self._get_attendance_contract(day)
        if (not contract or contract.company_id != self.company_id
                or contract.wage_type not in ('monthly', 'daily')
                or self._is_attendance_weekly_off(day)):
            return None
        calendar = contract.resource_calendar_id or self.resource_calendar_id
        tz = pytz.timezone(calendar.tz or self.env.user.tz or 'UTC')
        midnight = datetime.combine(day, time.min)
        def utc(hour):
            return tz.localize(midnight + timedelta(hours=hour)).astimezone(pytz.UTC).replace(tzinfo=None)
        sessions = [(utc(start), utc(end)) for start, end in self._get_attendance_work_periods(day)]
        if not sessions:
            return None
        if self.env['resource.calendar.leaves'].sudo().search_count([
            ('resource_id', '=', False), ('company_id', 'in', [False, self.company_id.id]),
            ('calendar_id', 'in', [False, calendar.id]),
            ('date_from', '<', utc(24)), ('date_to', '>', utc(0)),
        ]):
            return None
        attendance = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', self.id), ('check_in', '>=', utc(0)), ('check_in', '<', utc(24))])
        punches = _merge((att.check_in, att.check_out) for att in attendance
                         if att.check_out and att.worked_hours > 0)
        punches = _merge((max(a, start), min(b, end)) for a, b in punches for start, end in sessions
                         if a < end and b > start)
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id), ('state', '=', 'validate'),
            ('date_from', '<', utc(24)), ('date_to', '>', utc(0))])
        leave_intervals = [(leave.date_from, leave.date_to) for leave in leaves]
        effective_sessions = _subtract(sessions, leave_intervals)
        attended = any(a < end and b > start for a, b in punches for start, end in effective_sessions)
        return {'template': template, 'sessions': sessions, 'attendance': attendance,
                'punches': punches, 'leaves': leaves, 'leave_intervals': leave_intervals,
                'attended': attended}

    def _get_attendance_day_fraction(self, day, worked_hours, half_day_hours, full_day_hours):
        context = self._fine_only_attendance_context(day)
        if context is None:
            return super()._get_attendance_day_fraction(day, worked_hours, half_day_hours, full_day_hours)
        if not context['attended']:
            return 0.0
        # Explicit validated leave remains authoritative; the new option does
        # not turn an unpaid half into an additional attendance credit.
        leave_fraction = 0.0
        scheduled = sum((end - start).total_seconds() for start, end in context['sessions']) / 3600
        for leave in context['leaves']:
            if leave.request_unit_hours:
                leave_fraction += max(0, leave.request_hour_to - leave.request_hour_from) / scheduled
            else:
                leave_fraction += .5 if leave.request_unit_half else 1.0
        return max(0.0, 1.0 - min(1.0, leave_fraction))

    def _attendance_exception_components(self, day):
        context = self._fine_only_attendance_context(day)
        if context is None:
            return super()._attendance_exception_components(day)
        punches = context['punches']
        if (not context['attended'] or not punches
                or any(not att.check_out for att in context['attendance'])):
            return {}  # No absence fine, nor forecast of an open punch's end.
        template = context['template']
        totals = {'late': 0.0, 'early': 0.0, 'break': 0.0}
        for index, (start, end) in enumerate(context['sessions']):
            present = _merge((max(start, a), min(end, b)) for a, b in punches if a < end and b > start)
            if present:
                gaps = [('late', (start, present[0][0]),
                         template.late_grace_minutes if index == 0 else template.post_break_grace_minutes),
                        ('early', (present[-1][1], end), template.early_exit_grace_minutes)]
                gaps += [('break', (left[1], right[0]), 0) for left, right in zip(present, present[1:])]
            elif end <= punches[0][0]:
                gaps = [('late', (start, end), template.late_grace_minutes if index == 0 else 0)]
            elif start >= punches[-1][1]:
                gaps = [('early', (start, end), 0)]
            else:
                gaps = [('break', (start, end), 0)]
            for kind, interval, grace in gaps:
                missing = _subtract([interval], context['leave_intervals'])
                minutes = sum((b - a).total_seconds() for a, b in missing) / 60
                totals[kind] += max(0, int(round(minutes)) - grace)
        totals['late'] = totals['late'] if template.late_enabled else 0
        totals['early'] = totals['early'] if template.early_exit_enabled else 0
        totals['break'] = max(0, totals['break'] - template.allowed_break_minutes) if template.break_enabled else 0
        # Whole-day review keys keep existing fine approvals compatible. No
        # artificial worked/regularized hours are introduced by this policy.
        return {kind: {'hours': minutes / 60, 'coverage': []}
                for kind, minutes in totals.items() if minutes > 0}
