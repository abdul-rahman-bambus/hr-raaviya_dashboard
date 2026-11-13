"""Template checkout for Hourly employees with no assigned work calendar."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.osv import expression


class HourlyAutoCheckoutAttendance(models.Model):
    _inherit = 'hr.attendance'

    def _hourly_unscheduled_terms(self):
        self.ensure_one()
        if not self.check_in:
            return None
        employee = self.employee_id
        tz = pytz.timezone(employee._get_tz())
        local_in = pytz.UTC.localize(self.check_in).astimezone(tz)
        contract = employee._get_attendance_contract(local_in.date())
        if (not contract or contract.company_id != employee.company_id
                or contract.wage_type != 'hourly' or contract.resource_calendar_id
                or employee.resource_calendar_id):
            return None
        template = employee._get_attendance_automation_template(local_in.date())
        return local_in, tz, template

    def _hourly_auto_checkout_deadline(self, terms=None):
        terms = terms or self._hourly_unscheduled_terms()
        if not terms or not terms[2] or not terms[2].hourly_auto_checkout_enabled:
            return False
        local_in, tz, template = terms
        if template.hourly_auto_checkout_basis == 'hours':
            return self.check_in + timedelta(hours=template.hourly_auto_checkout_hours)
        minutes = round(template.hourly_auto_checkout_time * 60)
        cutoff = datetime.combine(local_in.date(), time.min) + timedelta(minutes=minutes)
        # The later occurrence is used at a DST fold; nonexistent wall times
        # map forward through the gap when converted to UTC.
        due = tz.localize(cutoff, is_dst=False).astimezone(pytz.UTC).replace(tzinfo=None)
        if due <= self.check_in:
            due = tz.localize(cutoff + timedelta(days=1), is_dst=False).astimezone(pytz.UTC).replace(tzinfo=None)
        return due

    @api.model
    def _cron_hourly_template_auto_check_out(self):
        now = fields.Datetime.now()
        closed = 0
        for attendance in self.search([('check_out', '=', False), ('employee_id.active', '=', True)], order='check_in, id'):
            due = attendance._hourly_auto_checkout_deadline()
            if not due or due > now:
                continue
            self.env.cr.execute('SELECT id FROM hr_attendance WHERE id = %s FOR UPDATE SKIP LOCKED', [attendance.id])
            if not self.env.cr.fetchone():
                continue
            attendance.invalidate_recordset(['check_in', 'check_out', 'employee_id'])
            if attendance.check_out:
                continue
            due = attendance._hourly_auto_checkout_deadline()
            if due and due <= now:
                attendance.with_context(
                    bambus_attendance_event_source='routine',
                    attendance_change_reason='Automatic checkout from hourly attendance template',
                ).write({'check_out': due, 'out_mode': 'auto_check_out'})
                closed += 1
        return closed

    @api.model
    def _cron_auto_check_out(self):
        # Native Odoo otherwise falls back to the company calendar when the
        # employee has none. Only unscheduled Hourly contracts are excluded;
        # scheduled employees continue through the unmodified native method.
        open_attendances = self.search([('check_out', '=', False),
            ('employee_id.company_id.auto_check_out', '=', True)])
        excluded = open_attendances.filtered(lambda attendance: bool(attendance._hourly_unscheduled_terms()))
        source = self.with_context(bambus_attendance_event_source='routine',
                                  bambus_native_auto_checkout_exclude_ids=excluded.ids)
        return super(HourlyAutoCheckoutAttendance, source)._cron_auto_check_out()

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        # This restriction exists only inside the native cron's context. It
        # does not affect ordinary dashboard, mobile or manual attendance reads.
        excluded = self.env.context.get('bambus_native_auto_checkout_exclude_ids')
        if excluded:
            domain = expression.AND([domain, [('id', 'not in', excluded)]])
        return super()._search(domain, offset=offset, limit=limit, order=order)
