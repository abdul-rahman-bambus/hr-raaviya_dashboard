# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    employee_tracking = fields.Boolean("Employee Tracking", default=False)

    def write(self, vals):
        res = super().write(vals)
        if 'employee_tracking' in vals and not vals.get('employee_tracking'):
            for company in self:
                employees = self.env['hr.employee'].sudo().search([
                    ('company_id', 'in', [company.id, False]),
                    ('track_employee', '=', True),
                ])
                if employees:
                    employees.write({'track_employee': False})
        return res


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    employee_tracking = fields.Boolean(
        related='company_id.employee_tracking',
        readonly=False,
        string="Employee Tracking"
    )

    def set_values(self):
        super().set_values()
        if not self.employee_tracking:
            company = self.company_id or self.env.company
            domain = [('track_employee', '=', True)]
            if company:
                domain.append(('company_id', 'in', [company.id, False]))
            employees = self.env['hr.employee'].sudo().search(domain)
            if employees:
                employees.write({'track_employee': False})
