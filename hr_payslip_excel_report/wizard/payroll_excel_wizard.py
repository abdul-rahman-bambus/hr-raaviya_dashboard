import calendar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PayslipReportWizard(models.TransientModel):
    _name = 'payslip.excel.wizard'
    _description = 'Payroll Reports'

    report_type = fields.Selection([
        ('summary', 'Payslip Summary'), ('review', 'Payroll Review'),
    ], required=True, default='summary')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    batch_id = fields.Many2one('hr.payslip.run', string='Payslip Batch')
    duration_type = fields.Selection([
        ('current', 'Current Month'), ('custom', 'Custom Date Range'),
    ], string='Report Period', required=True, default='current')
    start_date = fields.Date(default=lambda self: fields.Date.context_today(self).replace(day=1))
    end_date = fields.Date(default=lambda self: self._month_dates()[1])
    department_id = fields.Many2one('hr.department')
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    payslip_status = fields.Selection([
        ('all', 'All Except Rejected'), ('draft', 'Draft'), ('verify', 'Waiting'),
        ('done', 'Done'), ('cancel', 'Rejected'),
    ], required=True, default='all')

    def _month_dates(self):
        today = fields.Date.context_today(self)
        return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])

    def _period_dates(self):
        self.ensure_one()
        if self.duration_type == 'current':
            return self._month_dates()
        if not self.start_date or not self.end_date or self.start_date > self.end_date:
            raise ValidationError(_('Choose a valid start and end date.'))
        return self.start_date, self.end_date

    @api.constrains('duration_type', 'start_date', 'end_date')
    def _check_dates(self):
        for wizard in self:
            wizard._period_dates()

    @api.onchange('company_id')
    def _onchange_company(self):
        self.batch_id = False
        self.department_id = False
        self.employee_ids = False

    def _validate_scope(self):
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll_community.group_hr_payroll_community_user'):
            raise AccessError(_('Only payroll officers can export payroll reports.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('Select a company enabled in your current session.'))
        if any(employee.company_id != self.company_id for employee in self.employee_ids):
            raise ValidationError(_('All selected employees must belong to the report company.'))
        if self.department_id.company_id and self.department_id.company_id != self.company_id:
            raise ValidationError(_('The department must belong to the report company.'))
        self._period_dates()
        if self.batch_id:
            self.batch_id._check_draft_payroll_access()
            if self.batch_id.company_id != self.company_id:
                raise ValidationError(_('The batch must belong to the report company.'))

    def _selected_payslips(self):
        self._validate_scope()
        start, end = self._period_dates()
        domain = [('company_id', '=', self.company_id.id),
                  ('date_from', '>=', start), ('date_to', '<=', end)]
        domain += [('state', '!=', 'cancel')] if self.payslip_status == 'all' else [('state', '=', self.payslip_status)]
        if self.batch_id:
            domain.append(('payslip_run_id', '=', self.batch_id.id))
        if self.department_id:
            domain.append(('employee_id.department_id', '=', self.department_id.id))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        # Keep record rules: no sudo and no silently discarded matching payslips.
        return self.env['hr.payslip'].search(domain, order='employee_id, date_from, id')

    def _scope_employees(self):
        domain = [('company_id', '=', self.company_id.id)]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.employee_ids:
            domain.append(('id', 'in', self.employee_ids.ids))
        return self.env['hr.employee'].with_context(active_test=not bool(self.employee_ids)).search(domain)

    def _generate_xlsx(self):
        self._validate_scope()
        return self.env['report.hr_payslip_excel_report.payroll_review']._generate(self)

    def action_download_payslip_excel_report(self):
        self._validate_scope()
        return {
            'type': 'ir.actions.act_url', 'target': 'download',
            'url': '/my_excel/download?id=%s' % self.id,
        }
