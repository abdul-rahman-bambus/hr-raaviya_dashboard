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
    overtime_rate = fields.Monetary(currency_field="currency_id")

    fine_calculation_type = fields.Selection(
        CALCULATION_TYPES, required=True, default="fixed_hour"
    )
    fine_rate = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)

    @api.depends("employee_ids")
    def _compute_employee_count(self):
        for template in self:
            template.employee_count = len(template.employee_ids)

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
