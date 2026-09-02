from odoo import api, models

class EmployeeDetailsReport(models.AbstractModel):
    _name = 'report.custom_hr_payroll.employee_details_template'
    _description = 'Employee Details Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['hr.employee'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'hr.employee',
            'docs': docs,
        }
