from odoo import api, _, models, fields


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    employee_number = fields.Char(string="Employee ID", copy=False, index=True)
    blood_group = fields.Char(string="Blood Group")

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
