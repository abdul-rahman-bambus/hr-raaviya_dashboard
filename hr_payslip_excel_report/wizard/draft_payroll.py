import calendar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class DraftPayrollPreparation(models.TransientModel):
    _name = 'payroll.draft.preparation'
    _description = 'Prepare Monthly Draft Payroll'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    month = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(day=1),
                        help='Choose any date in the payroll month. The complete calendar month is used.')
    department_id = fields.Many2one('hr.department')
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    batch_id = fields.Many2one('hr.payslip.run', readonly=True)
    result = fields.Text(readonly=True)

    def _period(self):
        self.ensure_one()
        if not self.month:
            raise ValidationError(_('Choose the payroll month.'))
        return self.month.replace(day=1), self.month.replace(day=calendar.monthrange(self.month.year, self.month.month)[1])

    def _validate_scope(self):
        self.ensure_one()
        if not self.env.user.has_group('hr_payroll_community.group_hr_payroll_community_user'):
            raise AccessError(_('Only payroll officers can prepare payroll.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('Select a company enabled in your current session.'))
        self.employee_ids.check_access('read')
        if any(employee.company_id != self.company_id for employee in self.employee_ids):
            raise ValidationError(_('All selected employees must belong to the payroll company.'))
        if self.department_id.company_id and self.department_id.company_id != self.company_id:
            raise ValidationError(_('The department must belong to the payroll company.'))
        if self.department_id and any(employee.department_id != self.department_id for employee in self.employee_ids):
            raise ValidationError(_('Selected employees must belong to the selected department.'))
        start, end = self._period()
        if self.batch_id:
            self.batch_id._check_draft_payroll_access()
            if (self.batch_id.company_id != self.company_id or self.batch_id.credit_note
                    or self.batch_id.date_start != start or self.batch_id.date_end != end):
                raise ValidationError(_('The batch must match this company and complete calendar month, without refunds.'))
            if self.batch_id.state != 'draft':
                raise UserError(_('The batch is closed. Existing payroll has not been changed.'))
        return start, end

    @api.onchange('company_id', 'month')
    def _onchange_scope(self):
        self.batch_id = False
        self.result = False
        self.employee_ids = False
        self.department_id = False

    def _employees(self):
        domain = [('company_id', '=', self.company_id.id)]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.employee_ids:
            domain.append(('id', 'in', self.employee_ids.ids))
        return self.env['hr.employee'].with_context(active_test=not bool(self.employee_ids)).search(domain, order='name, id')

    def _batch(self, start, end):
        # Serialize preparation/recomputation for a company, including first creation.
        self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [self.company_id.id])
        if self.batch_id:
            self.batch_id.invalidate_recordset(['state'])
            self._validate_scope()
            return self.batch_id
        batches = self.env['hr.payslip.run'].search([
            ('company_id', '=', self.company_id.id), ('date_start', '=', start),
            ('date_end', '=', end), ('credit_note', '=', False)])
        if len(batches) > 1:
            raise UserError(_('Multiple batches match this month. Open the intended batch and use Prepare Draft Payroll there.'))
        if batches and batches.state != 'draft':
            raise UserError(_('This month already has a closed batch. It has not been changed.'))
        self.batch_id = batches or self.env['hr.payslip.run'].create({
            'name': _('Draft Payroll - %s') % start.strftime('%B %Y'),
            'company_id': self.company_id.id, 'date_start': start, 'date_end': end,
            'state': 'draft', 'credit_note': False})
        return self.batch_id

    def _segments(self, employee, start, end, batch):
        contracts = self.env['hr.contract'].search([
            ('employee_id', '=', employee.id), ('company_id', '=', self.company_id.id),
            ('state', 'in', ['open', 'close']), ('date_start', '<=', end),
            '|', ('date_end', '=', False), ('date_end', '>=', start)], order='date_start, id')
        if not contracts:
            raise UserError(_('No running/expired contract overlaps the month.'))
        segments = []
        previous_end = None
        for contract in contracts:
            first, last = max(start, contract.date_start), min(end, contract.date_end or end)
            if previous_end and first <= previous_end:
                raise UserError(_('Contracts overlap; correct the contract dates before generating payroll.'))
            if not contract.struct_id:
                raise UserError(_('Contract %s has no salary structure.') % contract.name)
            previous_end = last
            overlapping = self.env['hr.payslip'].search([
                ('employee_id', '=', employee.id), ('company_id', '=', self.company_id.id),
                ('state', '!=', 'cancel'), ('credit_note', '=', False),
                ('date_from', '<=', last), ('date_to', '>=', first)])
            if len(overlapping) > 1:
                raise UserError(_('Multiple overlapping payslips already exist; review them before proceeding.'))
            existing = overlapping
            if existing and (existing.date_from != first or existing.date_to != last or existing.contract_id != contract):
                raise UserError(_('An existing payslip overlaps this contract period; it has not been changed.'))
            if existing and existing.state != 'draft':
                raise UserError(_('An existing waiting/finalized payslip covers this period; it has not been changed.'))
            if existing.payslip_run_id and existing.payslip_run_id != batch:
                raise UserError(_('An existing draft belongs to another batch; it has not been moved.'))
            segments.append((contract, first, last, existing))
        return segments

    def _create_slip(self, employee, contract, start, end, batch):
        model = self.env['hr.payslip'].with_company(self.company_id)
        data = model.with_context(contract=True).onchange_employee_id(
            fields.Date.to_string(start), fields.Date.to_string(end), employee.id, contract_id=contract.id)['value']
        values = {
            'name': data['name'], 'employee_id': employee.id, 'contract_id': contract.id,
            'company_id': self.company_id.id, 'struct_id': contract.struct_id.id,
            'date_from': start, 'date_to': end, 'payslip_run_id': batch.id, 'state': 'draft',
            'credit_note': False, 'paid': False,
            'input_line_ids': [(0, 0, row) for row in (data.get('input_line_ids') or [])],
            'worked_days_line_ids': [(0, 0, row) for row in (data.get('worked_days_line_ids') or [])],
        }
        if 'journal_id' in model._fields:
            journal = contract.journal_id if 'journal_id' in contract._fields else False
            journal = journal or self.env['account.journal'].search([('company_id', '=', self.company_id.id), ('type', '=', 'general')], limit=1)
            if not journal:
                raise UserError(_('Configure a salary/general journal for this company.'))
            values['journal_id'] = journal.id
        slip = model.create(values)
        slip.action_compute_sheet()
        return slip

    def _review_notes(self, employees, start, end):
        if not employees:
            return []
        data = self.env['payslip.excel.wizard'].create({
            'company_id': self.company_id.id, 'duration_type': 'custom',
            'start_date': start, 'end_date': end, 'employee_ids': [(6, 0, employees.ids)],
            'payslip_status': 'draft', 'batch_id': self.batch_id.id, 'report_type': 'review'})
        report = self.env['report.hr_payslip_excel_report.payroll_review']._data(data)
        return [('%s: %s — %s' % (row.get('name', ''), row['issue'], row.get('message', '')))
                for row in report['exceptions']]

    def action_generate(self):
        start, end = self._validate_scope()
        employees = self._employees()
        if not employees:
            raise UserError(_('No employees match this selection.'))
        batch = self._batch(start, end)
        created = reused = 0
        issues = []
        successful = self.env['hr.employee']
        for employee in employees:
            try:
                with self.env.cr.savepoint():
                    segments = self._segments(employee, start, end, batch)
                    employee_created = employee_reused = 0
                    for contract, first, last, existing in segments:
                        if existing:
                            if not existing.payslip_run_id:
                                existing.payslip_run_id = batch
                            employee_reused += 1
                        else:
                            self._create_slip(employee, contract, first, last, batch)
                            employee_created += 1
                created += employee_created
                reused += employee_reused
                successful |= employee
            except AccessError:
                raise
            except Exception as error:
                issues.append('%s: %s' % (employee.name, str(error)))
        issues += self._review_notes(successful, start, end)
        self.result = _('Created: %(created)s. Reused without recomputing: %(reused)s. All prepared payslips remain Draft.\nUse Recompute Drafts after attendance or HR changes.\n\nAttention:\n%(issues)s') % {
            'created': created, 'reused': reused, 'issues': '\n'.join(issues) or _('No issues detected.')}
        return self._open_action()

    def action_recompute(self):
        start, end = self._validate_scope()
        if not self.batch_id:
            raise UserError(_('Generate or select a batch first.'))
        batch = self._batch(start, end)
        employees = self._employees()
        slips = batch.slip_ids.filtered(lambda slip: slip.employee_id in employees and slip.state == 'draft' and not slip.credit_note)
        issues = []
        computed = 0
        for slip in slips:
            try:
                with self.env.cr.savepoint():
                    # Verify the same duplicate/contract boundaries as generation.
                    segments = self._segments(slip.employee_id, start, end, batch)
                    if slip not in self.env['hr.payslip'].browse([item[3].id for item in segments if item[3]]):
                        raise UserError(_('The draft no longer matches the selected contracts.'))
                    slip.action_compute_sheet()
                computed += 1
            except AccessError:
                raise
            except Exception as error:
                issues.append('%s: %s' % (slip.employee_id.name, str(error)))
        issues += self._review_notes(slips.employee_id, start, end)
        self.result = _('Recomputed: %(count)s draft payslips. Waiting/finalized payslips were not changed.\n\nAttention:\n%(issues)s') % {
            'count': computed, 'issues': '\n'.join(issues) or _('No issues detected.')}
        return self._open_action()

    def _open_action(self):
        return {'type': 'ir.actions.act_window', 'name': _('Prepare Draft Payroll'),
                'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}

    def action_open_batch(self):
        self._validate_scope()
        if not self.batch_id:
            raise UserError(_('Generate a batch first.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'hr.payslip.run',
                'res_id': self.batch_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_report(self):
        start, end = self._validate_scope()
        if not self.batch_id:
            raise UserError(_('Generate a batch first.'))
        report = self.env['payslip.excel.wizard'].create({
            'company_id': self.company_id.id, 'duration_type': 'custom',
            'start_date': start, 'end_date': end, 'employee_ids': [(6, 0, self._employees().ids)],
            'batch_id': self.batch_id.id, 'report_type': 'review', 'payslip_status': 'draft'})
        return {'type': 'ir.actions.act_window', 'name': _('Payroll Reports'),
                'res_model': report._name, 'res_id': report.id, 'view_mode': 'form', 'target': 'new'}
