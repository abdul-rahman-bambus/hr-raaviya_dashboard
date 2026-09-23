from odoo import api, fields, models
from odoo.exceptions import ValidationError


CALCULATION_TYPES = [
    ("fixed", "Fixed Amount"),
    ("fixed_hour", "Fixed Amount per Hour"),
    ("half_day", "Half Day"),
    ("full_day", "Full Day"),
    ("regularize", "Regularize"),
    ("salary_1", "1x Salary"),
    ("salary_1_5", "1.5x Salary"),
    ("salary_2", "2x Salary"),
]


class AttendanceAutomationTemplate(models.Model):
    _name = "bambus.attendance.automation.template"
    _description = "Attendance Automation Template"
    _order = "company_id, name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    date_from = fields.Date(string="Effective From")
    date_to = fields.Date(string="Effective Until")
    employee_ids = fields.One2many(
        "hr.employee", "attendance_automation_template_id", string="Assigned Employees"
    )
    employee_count = fields.Integer(compute="_compute_employee_count")

    late_enabled = fields.Boolean(string="Late Entry Rule", default=True)
    late_grace_minutes = fields.Integer(string="Late Entry Grace (Minutes)", default=0)
    early_exit_enabled = fields.Boolean(string="Early Exit Rule", default=True)
    early_exit_grace_minutes = fields.Integer(string="Early Exit Grace (Minutes)", default=0)
    break_enabled = fields.Boolean(string="Break Rule")
    allowed_break_minutes = fields.Integer(string="Allowed Break (Minutes)", default=0)

    overtime_enabled = fields.Boolean(string="Overtime Rule", default=True)
    minimum_overtime_minutes = fields.Integer(string="Minimum Overtime (Minutes)", default=0)
    weekend_overtime = fields.Boolean(string="Weekend / Holiday Overtime")
    overtime_calculation_type = fields.Selection(
        CALCULATION_TYPES, required=True, default="fixed_hour"
    )
    overtime_rate_policy = fields.Selection([
        ("contract", "Contract OT Rate"),
        ("fixed", "Fixed Template Rate"),
        ("salary_slab", "Salary Range / Slab"),
        ("salary_multiplier", "Salary Multiplier"),
    ], required=True, default="contract")
    overtime_salary_basis = fields.Selection([
        ("monthly", "Monthly Contract Wage"),
        ("daily", "Daily Contract Wage"),
        ("hourly", "Hourly Contract Rate"),
    ], required=True, default="monthly")
    overtime_rate = fields.Monetary(currency_field="currency_id")
    overtime_slab_ids = fields.One2many(
        "bambus.attendance.overtime.rate.slab", "template_id", string="OT Salary Slabs"
    )

    fine_calculation_type = fields.Selection(
        CALCULATION_TYPES, required=True, default="fixed_hour"
    )
    fine_rate = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)

    @api.depends("employee_ids")
    def _compute_employee_count(self):
        for template in self:
            template.employee_count = len(template.employee_ids)

    def _salary_basis_amount(self, contract):
        self.ensure_one()
        if not contract:
            return 0.0
        if self.overtime_salary_basis == "daily":
            return float(getattr(contract, "daily_wage", 0.0) or 0.0)
        if self.overtime_salary_basis == "hourly":
            return float(getattr(contract, "hourly_rate", 0.0) or 0.0)
        return float(contract.wage or 0.0)

    def resolve_overtime_rate(self, contract):
        """Return the configured rate, salary basis, and matching slab."""
        self.ensure_one()
        salary_amount = self._salary_basis_amount(contract)
        if self.overtime_rate_policy == "fixed":
            return self.overtime_rate or 0.0, salary_amount, self.env[
                "bambus.attendance.overtime.rate.slab"
            ]
        if self.overtime_rate_policy == "salary_slab":
            slab = self.overtime_slab_ids.filtered(
                lambda item: item.salary_from <= salary_amount
                and (not item.has_maximum or salary_amount <= item.salary_to)
            )[:1]
            return (slab.rate or 0.0) if slab else 0.0, salary_amount, slab
        return float(getattr(contract, "overtime_rate", 0.0) or 0.0), salary_amount, self.env[
            "bambus.attendance.overtime.rate.slab"
        ]

    @api.constrains(
        "date_from", "date_to", "late_grace_minutes", "early_exit_grace_minutes",
        "allowed_break_minutes", "minimum_overtime_minutes", "overtime_rate", "fine_rate",
    )
    def _check_values(self):
        for template in self:
            if template.date_from and template.date_to and template.date_to < template.date_from:
                raise ValidationError("Effective Until cannot be before Effective From.")
            values = (
                template.late_grace_minutes,
                template.early_exit_grace_minutes,
                template.allowed_break_minutes,
                template.minimum_overtime_minutes,
                template.overtime_rate,
                template.fine_rate,
            )
            if any(value < 0 for value in values):
                raise ValidationError("Automation rule values cannot be negative.")


class AttendanceOvertimeRateSlab(models.Model):
    _name = "bambus.attendance.overtime.rate.slab"
    _description = "Attendance Overtime Salary Slab"
    _order = "salary_from, id"

    template_id = fields.Many2one(
        "bambus.attendance.automation.template", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="template_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="template_id.currency_id", readonly=True)
    salary_from = fields.Monetary(required=True, currency_field="currency_id")
    has_maximum = fields.Boolean(string="Has Maximum", default=True)
    salary_to = fields.Monetary(currency_field="currency_id")
    rate = fields.Monetary(string="OT Rate / Hour", required=True, currency_field="currency_id")

    @api.constrains("salary_from", "salary_to", "has_maximum", "rate", "template_id")
    def _check_salary_ranges(self):
        for slab in self:
            if slab.salary_from < 0 or slab.rate < 0:
                raise ValidationError("Salary limits and overtime rates cannot be negative.")
            if slab.has_maximum and slab.salary_to < slab.salary_from:
                raise ValidationError("To Salary cannot be lower than From Salary.")
            siblings = slab.template_id.overtime_slab_ids.sorted("salary_from")
            open_ended = siblings.filtered(lambda item: not item.has_maximum)
            if len(open_ended) > 1:
                raise ValidationError("Only one open-ended overtime salary slab is allowed.")
            previous = False
            for item in siblings:
                if previous and (
                    not previous.has_maximum or item.salary_from <= previous.salary_to
                ):
                    raise ValidationError("Overtime salary slabs cannot overlap.")
                previous = item


class ResCompany(models.Model):
    _inherit = "res.company"

    attendance_automation_template_id = fields.Many2one(
        "bambus.attendance.automation.template",
        string="Default Attendance Automation",
        domain="[('company_id', '=', id)]",
    )


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    attendance_automation_template_id = fields.Many2one(
        "bambus.attendance.automation.template",
        string="Attendance Automation",
        domain="[('company_id', '=', company_id)]",
        groups="hr.group_hr_user",
    )

    def _get_attendance_automation_template(self, day=None):
        self.ensure_one()
        day = fields.Date.to_date(day or fields.Date.context_today(self))
        candidates = (
            self.attendance_automation_template_id,
            self.company_id.attendance_automation_template_id,
        )
        for template in candidates:
            if (
                template
                and template.active
                and (not template.date_from or template.date_from <= day)
                and (not template.date_to or template.date_to >= day)
            ):
                return template
        return self.env["bambus.attendance.automation.template"]
