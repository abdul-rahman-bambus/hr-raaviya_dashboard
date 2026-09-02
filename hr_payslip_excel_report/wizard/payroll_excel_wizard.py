from odoo import fields, models, _
from odoo.exceptions import UserError


class PayslipReportWizard(models.TransientModel):
    _name = 'payslip.excel.wizard'
    _description = 'Generate Payslips Excel Report'

    duration_type = fields.Selection([
        ('current', 'Current Month'),
        ('custom', 'Custom Month'),
    ], string="Report Duration", required="True")

    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    
    
    def action_download_payslip_excel_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': "/my_excel/download?id=%s" %self.id,
        }