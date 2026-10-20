from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    # Also supports installations without hr_multi_company's batch extension.
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def _check_draft_payroll_access(self):
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll_community.group_hr_payroll_community_user'):
            raise AccessError(_('Only payroll officers can prepare payroll.'))
        self.check_access('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('Select a batch in a company enabled in your current session.'))

    def action_prepare_draft_payroll(self):
        self._check_draft_payroll_access()
        if self.state != 'draft' or self.credit_note:
            raise UserError(_('Use an open, non-refund batch for draft payroll preparation.'))
        wizard = self.env['payroll.draft.preparation'].create({
            'company_id': self.company_id.id, 'month': self.date_start, 'batch_id': self.id})
        wizard._validate_scope()
        return wizard._open_action()

    def action_open_payroll_report(self):
        self._check_draft_payroll_access()
        wizard = self.env['payslip.excel.wizard'].create({
            'company_id': self.company_id.id, 'batch_id': self.id,
            'duration_type': 'custom', 'start_date': self.date_start,
            'end_date': self.date_end, 'payslip_status': 'all', 'report_type': 'review'})
        return {'type': 'ir.actions.act_window', 'name': _('Payroll Reports'),
                'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}
