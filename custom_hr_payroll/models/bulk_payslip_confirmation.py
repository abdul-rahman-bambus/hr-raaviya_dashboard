from collections import defaultdict

from odoo import _, models
from odoo.exceptions import AccessError, UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _check_bulk_confirmation(self):
        if not self.env.user.has_group('hr_payroll_community.group_hr_payroll_community_user'):
            raise AccessError(_('Only payroll officers can confirm payslips.'))
        self.check_access('write')
        if not self or self.exists() != self:
            raise UserError(_('Select the payslips to confirm.'))
        if len(self.company_id) != 1 or self.company_id not in self.env.companies:
            raise UserError(_('Select payslips from one enabled company.'))
        if any(slip.state not in ('draft', 'verify') for slip in self):
            raise UserError(_('Select only Draft or Waiting payslips. Done and Rejected payslips cannot be bulk confirmed.'))
        if any(not slip.line_ids.filtered(lambda line: line.code == 'NET') for slip in self):
            raise UserError(_('Compute and review every selected payslip before confirming.'))

    def action_open_bulk_confirmation(self):
        self._check_bulk_confirmation()
        wizard = self.env['hr.payslip.bulk.confirm.wizard'].create({'payslip_ids': [(6, 0, self.ids)]})
        return {'type': 'ir.actions.act_window', 'name': _('Confirm Payslips'),
                'res_model': wizard._name, 'res_id': wizard.id,
                'views': [(False, 'form')], 'target': 'new'}

    def _bulk_confirm_reviewed_payslips(self):
        self._check_bulk_confirmation()
        # Standard confirmation can recompute and invoke accounting/loan hooks.
        # Roll back the entire selection if any reviewed amount changes.
        def amounts(slip):
            result = defaultdict(float)
            for line in slip.line_ids:
                result[(line.salary_rule_id.id, line.code, line.category_id.id)] += line.total
            return result

        with self.env.cr.savepoint():
            self.env.cr.execute('SELECT id FROM hr_payslip WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset(['state', 'line_ids'])
            self._check_bulk_confirmation()
            saved = {slip.id: amounts(slip) for slip in self}
            for slip in self:
                slip.action_payslip_done()
                current = amounts(slip)
                previous = saved[slip.id]
                if any(slip.company_id.currency_id.compare_amounts(previous.get(key, 0), current.get(key, 0))
                       for key in previous.keys() | current.keys()):
                    raise UserError(_(
                        'Salary changed for %(employee)s during confirmation. Nothing was confirmed. '
                        'Compute Sheet, review the updated report, then confirm again.', employee=slip.employee_id.name))
        return True
