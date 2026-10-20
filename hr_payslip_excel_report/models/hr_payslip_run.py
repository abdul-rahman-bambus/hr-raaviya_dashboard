from odoo import fields, models


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    # Keep the stored company field from PR #121 so withdrawing its UI never
    # drops existing batch ownership on installations without hr_multi_company.
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
