from odoo import api, fields, models


class BulkPayslipConfirmation(models.TransientModel):
    _name = 'hr.payslip.bulk.confirm.wizard'
    _description = 'Confirm Selected Payslips'

    payslip_ids = fields.Many2many('hr.payslip', required=True, readonly=True)
    slip_count = fields.Integer(compute='_compute_summary', string='Selected Payslips')
    company_id = fields.Many2one('res.company', compute='_compute_summary')
    currency_id = fields.Many2one(related='company_id.currency_id')
    total_net = fields.Monetary(compute='_compute_summary', string='Total Net Salary')

    @api.depends('payslip_ids', 'payslip_ids.line_ids.total', 'payslip_ids.line_ids.code')
    def _compute_summary(self):
        for wizard in self:
            wizard.slip_count = len(wizard.payslip_ids)
            wizard.company_id = wizard.payslip_ids[:1].company_id
            wizard.total_net = sum(wizard.payslip_ids.line_ids.filtered(lambda line: line.code == 'NET').mapped('total'))

    def action_confirm(self):
        self.ensure_one()
        self.payslip_ids._bulk_confirm_reviewed_payslips()
        return {'type': 'ir.actions.act_window_close'}
