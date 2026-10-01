from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _bambus_hourly_billable_hours(self, employee, contract, date_from, date_to):
        """Use HR-approved daily payable hours while retaining the contract cap."""
        billable, attendance_days = super()._bambus_hourly_billable_hours(
            employee, contract, date_from, date_to
        )
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        approved = self.env["bambus.hr.attendance.sheet.line"].sudo().search([
            ("employee_id", "=", employee.id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("hourly_pay_state", "=", "approved"),
        ])
        if not approved:
            return billable, attendance_days

        tzname = (
            contract.resource_calendar_id.tz
            if contract.resource_calendar_id and contract.resource_calendar_id.tz
            else self.env.user.tz or "UTC"
        )
        timezone = pytz.timezone(tzname)
        start = timezone.localize(datetime.combine(date_from, time.min))
        end = timezone.localize(datetime.combine(date_to + timedelta(days=1), time.min))
        attendances = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", start.astimezone(pytz.UTC).replace(tzinfo=None)),
            ("check_in", "<", end.astimezone(pytz.UTC).replace(tzinfo=None)),
        ])
        raw_by_day = defaultdict(float)
        for attendance in attendances:
            local_day = fields.Datetime.context_timestamp(
                self.with_context(tz=tzname), attendance.check_in
            ).date()
            raw_by_day[local_day] += attendance.worked_hours or 0.0

        limit = float(getattr(contract, "hourly_wage_hour_limit", 0.0) or 0.0)
        for line in approved:
            original = raw_by_day.get(line.date, 0.0)
            original = min(original, limit) if limit > 0 else original
            corrected = max(line.hourly_pay_hours or 0.0, 0.0)
            corrected = min(corrected, limit) if limit > 0 else corrected
            billable += corrected - original
            if corrected and not original:
                attendance_days += 1
            elif original and not corrected:
                attendance_days -= 1
        return max(billable, 0.0), max(attendance_days, 0)
