from odoo import api, _, models, fields


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    employee_number = fields.Char(string="Employee ID", copy=False, index=True)
    blood_group = fields.Char(string="Blood Group")

    def _get_attendance_contract(self, day):
        """Contract valid on the attendance date, including historical contracts."""
        self.ensure_one()
        day = fields.Date.to_date(day)
        return self.env["hr.contract"].sudo().search([
            ("employee_id", "=", self.id),
            ("state", "!=", "cancel"),
            "|", ("date_start", "=", False), ("date_start", "<=", day),
            "|", ("date_end", "=", False), ("date_end", ">=", day),
        ], order="date_start desc, id desc", limit=1)

    def _get_attendance_work_periods(self, day):
        """Assigned work periods on a date, before holidays or personal leave."""
        self.ensure_one()
        day = fields.Date.to_date(day)
        contract = self._get_attendance_contract(day)
        calendar = contract.resource_calendar_id or self.resource_calendar_id
        if not calendar:
            return []
        week_type = str(self.env["resource.calendar.attendance"].get_week_type(day))
        rules = calendar.attendance_ids.filtered(
            lambda rule: not rule.display_type
            and rule.day_period not in ("lunch", "break")
            and rule.dayofweek == str(day.weekday())
            and (not rule.date_from or rule.date_from <= day)
            and (not rule.date_to or rule.date_to >= day)
            and (not calendar.two_weeks_calendar or rule.week_type == week_type)
        )
        return sorted((rule.hour_from, rule.hour_to) for rule in rules)

    def _is_attendance_weekly_off(self, day):
        """Schedule-based fallback when no automation template is effective."""
        self.ensure_one()
        return not self._get_attendance_work_periods(day)

    def _get_attendance_day_pay_hours(self, day, worked_hours):
        """Classification hours; extensions may add explicitly excused time.

        Actual attendance/hourly billable hours must never use this value.
        """
        self.ensure_one()
        return float(worked_hours or 0.0)

    def _attendance_exception_components(self, day):
        """Optional session review engine supplied by the HR dashboard module."""
        return None

    def _is_paid_attendance_weekly_off(self, day, contract):
        """Normal day credit; callers exclude overlapping public holidays."""
        self.ensure_one()
        day = fields.Date.to_date(day)
        return bool(contract and contract.wage_type == 'monthly'
                    and (not contract.date_start or day >= contract.date_start)
                    and (not contract.date_end or day <= contract.date_end)
                    and self._is_attendance_weekly_off(day))

    def _is_paid_attendance_public_holiday(self, day, contract):
        """Legacy behavior has no automatic unworked public-holiday credit."""
        self.ensure_one()
        return False

    def _get_attendance_hourly_limit(self, day, contract):
        self.ensure_one()
        return float(contract.hourly_wage_hour_limit or 0.0) if contract else 0.0

    _sql_constraints = [
        ("employee_number_unique", "unique(employee_number)", "Employee ID must be unique."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for values in vals_list:
            if not values.get("employee_number"):
                values["employee_number"] = sequence.next_by_code("hr.employee.number")
        return super().create(vals_list)
