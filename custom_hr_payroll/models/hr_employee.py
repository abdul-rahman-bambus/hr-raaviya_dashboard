from odoo import _, models, fields


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    employee_number = fields.Char(string="Employee ID")
    blood_group = fields.Char(string="Blood Group")
    