from odoo import fields, models


class HrEmployeePublicInherit(models.Model):
    _inherit = "hr.employee.public"

    is_enrolled = fields.Boolean(
        related="employee_id.is_enrolled",
        readonly=True,
        compute_sudo=True,
    )
    last_photo_update_time = fields.Datetime(
        related="employee_id.last_photo_update_time",
        readonly=True,
        compute_sudo=True,
    )
