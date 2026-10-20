from calendar import monthrange
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestDraftPayrollPreparation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Draft payroll calendar', 'tz': 'UTC', 'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                        'hour_from': 9, 'hour_to': 17}) for day in range(6)]})
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Draft payroll rules', 'weekly_off_source': 'weekdays',
            'weekly_off_sunday': True, 'monthly_paid_weekly_off': True,
            'monthly_paid_public_holiday': True, 'overtime_enabled': False,
            'late_enabled': False, 'early_exit_enabled': False,
            'full_day_basis': 'fixed', 'full_day_hours': 8, 'half_day_hours': 4})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Draft payroll employee', 'resource_calendar_id': cls.calendar.id,
            'attendance_automation_template_id': cls.template.id})
        cls.env['hr.salary.rule']._bambus_use_automation_amounts()
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Draft payroll structure', 'code': 'DRAFT_PREP_TEST', 'parent_id': False,
            'rule_ids': [(6, 0, [cls.env.ref('hr_payroll_community.' + ref).id for ref in
                                ('hr_rule_basic', 'hr_rule_taxable', 'hr_rule_net')])]})
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Draft payroll contract', 'employee_id': cls.employee.id,
            'date_start': '2024-01-01', 'wage': 12000, 'wage_type': 'monthly',
            'resource_calendar_id': cls.calendar.id, 'struct_id': cls.structure.id, 'state': 'open'})
        cls.model = cls.env['payroll.draft.preparation']

    def wizard(self, **values):
        return self.model.create({'month': '2026-10-01', 'employee_ids': [(6, 0, self.employee.ids)], **values})

    def punches(self, start, end):
        day = fields.Date.to_date(start)
        end = fields.Date.to_date(end)
        values = []
        while day <= end:
            if day.weekday() != 6:
                values.append({'employee_id': self.employee.id, 'check_in': datetime.combine(day, time(9)),
                               'check_out': datetime.combine(day, time(17))})
            day += timedelta(days=1)
        return self.env['hr.attendance'].create(values)

    def test_month_lengths_and_repeat_generation_stay_draft(self):
        for year, month in [(2025, 2), (2024, 2), (2026, 4), (2026, 10)]:
            with self.subTest(year=year, month=month):
                start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
                self.punches(start, end)
                wizard = self.wizard(month=start)
                wizard.action_generate()
                batch = wizard.batch_id
                slip = batch.slip_ids.filtered(lambda row: row.employee_id == self.employee)
                self.assertEqual(len(slip), 1, wizard.result)
                self.assertEqual((batch.state, slip.state), ('draft', 'draft'))
                self.assertFalse(batch.credit_note or slip.credit_note or slip.paid)
                self.assertEqual((slip.date_from, slip.date_to), (start, end))
                self.assertAlmostEqual(slip.line_ids.filtered(lambda line: line.code == 'NET').total, 12000, places=2)
                original = [(line.id, line.total) for line in slip.line_ids]
                repeated = self.wizard(month=start)
                repeated.action_generate()
                self.assertEqual(repeated.batch_id, batch)
                self.assertEqual(batch.slip_ids, slip)
                self.assertEqual([(line.id, line.total) for line in slip.line_ids], original)

    def test_explicit_recompute_refreshes_drafts_and_report_uses_same_salary(self):
        wizard = self.wizard()
        wizard.action_generate()
        slip = wizard.batch_id.slip_ids
        before = slip.line_ids.filtered(lambda line: line.code == 'NET').total
        self.punches('2026-10-01', '2026-10-31')
        wizard.action_generate()  # existing draft is preserved until explicit recompute
        self.assertEqual(slip.line_ids.filtered(lambda line: line.code == 'NET').total, before)
        wizard.action_recompute()
        self.assertEqual(slip.state, 'draft')
        self.assertAlmostEqual(slip.line_ids.filtered(lambda line: line.code == 'NET').total, 12000, places=2)
        action = wizard.action_report()
        report_wizard = self.env['payslip.excel.wizard'].browse(action['res_id'])
        self.assertEqual((report_wizard.payslip_status, report_wizard.batch_id), ('draft', wizard.batch_id))
        self.assertEqual(report_wizard._selected_payslips(), slip)
        row = self.env['report.hr_payslip_excel_report.payroll_review']._data(report_wizard)['register'][0]
        self.assertAlmostEqual(row['net'], slip.line_ids.filtered(lambda line: line.code == 'NET').total)
        self.assertTrue(report_wizard._generate_xlsx().startswith(b'PK'))
        # The legacy generator still works and computes identical salary rules.
        manual_batch = self.env['hr.payslip.run'].create({
            'name': 'Legacy generator', 'company_id': self.env.company.id,
            'date_start': '2026-10-01', 'date_end': '2026-10-31'})
        legacy = self.env['hr.payslip.employees'].with_context(active_id=manual_batch.id).create({
            'employee_ids': [(6, 0, self.employee.ids)]})
        legacy.action_compute_sheet()
        self.assertEqual({line.code: line.total for line in manual_batch.slip_ids.line_ids},
                         {line.code: line.total for line in slip.line_ids})
        self.assertEqual(report_wizard._selected_payslips(), slip)  # batch isolation

    def test_partial_and_nonoverlapping_contract_segments(self):
        self.contract.date_end = '2026-10-10'
        self.contract.state = 'close'
        second = self.contract.copy({'date_start': '2026-10-20', 'date_end': False, 'state': 'open', 'resource_calendar_id': self.calendar.id})
        self.punches('2026-10-01', '2026-10-31')
        wizard = self.wizard()
        wizard.action_generate()
        slips = wizard.batch_id.slip_ids.sorted('date_from')
        self.assertEqual(len(slips), 2, wizard.result)
        self.assertEqual([(slip.date_from.day, slip.date_to.day) for slip in slips], [(1, 10), (20, 31)])
        self.assertEqual(slips.contract_id, self.contract | second)
        self.assertAlmostEqual(sum(slips.mapped('total_regular_pay_amount')), 12000 * 22 / 31, msg=str([(s.date_from, s.date_to, s.total_regular_pay_amount, s.contract_id.wage, s.contract_id.resource_calendar_id.id, s.employee_id.resource_calendar_id.id, s.total_worked_hours_excl_ot) for s in slips]))
        wizard.action_generate()
        self.assertEqual(len(wizard.batch_id.slip_ids), 2)

    def test_missing_structure_or_contract_is_flagged_without_blocking_valid_staff(self):
        missing = self.env['hr.employee'].create({'name': 'No contract payroll employee'})
        invalid = self.env['hr.employee'].create({'name': 'No structure payroll employee'})
        self.contract.copy({'employee_id': invalid.id, 'struct_id': False, 'state': 'open'})
        wizard = self.wizard(employee_ids=[(6, 0, (self.employee | missing | invalid).ids)])
        wizard.action_generate()
        self.assertEqual(wizard.batch_id.slip_ids.employee_id, self.employee)
        self.assertIn(missing.name, wizard.result)
        self.assertIn('salary structure', wizard.result)

    def test_duplicate_overlap_and_protected_slips_are_not_changed(self):
        wizard = self.wizard()
        wizard.action_generate()
        slip = wizard.batch_id.slip_ids
        saved = [(line.id, line.total) for line in slip.line_ids]
        for state in ['verify', 'done']:
            slip.state = state
            wizard.action_generate()
            wizard.action_recompute()
            self.assertEqual(slip.state, state)
            self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
        slip.state = 'draft'
        duplicate = slip.copy({'payslip_run_id': False})
        wizard.action_generate()
        self.assertIn('Multiple overlapping payslips', wizard.result)
        self.assertEqual(len(wizard.batch_id.slip_ids), 1)
        duplicate.unlink()
        slip.date_to = '2026-10-15'
        wizard.action_generate()
        self.assertIn('overlaps this contract period', wizard.result)
        self.assertEqual(len(wizard.batch_id.slip_ids), 1)

    def test_unassigned_draft_reused_but_other_batch_draft_not_moved(self):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'contract_id': self.contract.id,
            'date_from': '2026-10-01', 'date_to': '2026-10-31', 'struct_id': self.structure.id})
        wizard = self.wizard()
        wizard.action_generate()
        self.assertEqual(slip.payslip_run_id, wizard.batch_id)
        other = self.env['hr.payslip.run'].create({
            'name': 'Different batch', 'company_id': self.env.company.id,
            'date_start': '2026-09-01', 'date_end': '2026-09-30'})
        slip.payslip_run_id = other
        wizard.action_generate()
        self.assertEqual(slip.payslip_run_id, other)
        self.assertIn('another batch', wizard.result)

    def test_cancelled_slips_do_not_block_but_closed_or_multiple_batches_do(self):
        wizard = self.wizard()
        wizard.action_generate()
        wizard.batch_id.slip_ids.state = 'cancel'
        wizard.action_generate()
        self.assertEqual(len(wizard.batch_id.slip_ids.filtered(lambda row: row.state == 'draft')), 1)
        wizard.batch_id.state = 'close'
        with self.assertRaises(UserError):
            self.wizard().action_generate()
        with self.assertRaises(UserError):
            wizard.action_recompute()
        wizard.batch_id.state = 'draft'
        wizard.batch_id.copy({'name': 'Duplicate batch'})
        with self.assertRaises(UserError):
            self.wizard().action_generate()

    def test_scope_permissions_company_and_contract_overlap(self):
        basic = new_test_user(self.env, login='draft_payroll_basic', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.wizard().with_user(basic).action_generate()
        other_company = self.env['res.company'].create({'name': 'Other draft payroll'})
        with self.assertRaises(AccessError):
            self.wizard(company_id=other_company.id).with_context(allowed_company_ids=[self.env.company.id]).action_generate()
        other_employee = self.env['hr.employee'].create({'name': 'Other draft payroll employee', 'company_id': other_company.id})
        with self.assertRaises(ValidationError):
            self.wizard(employee_ids=[(6, 0, other_employee.ids)]).action_generate()
        # Simulate overlapping legacy/imported data, bypassing core's newer constraint.
        overlapping = self.contract.copy({'date_start': '2026-10-10', 'state': 'draft'})
        self.env.cr.execute("UPDATE hr_contract SET state = 'close' WHERE id = %s", [overlapping.id])
        overlapping.invalidate_recordset(['state'])
        wizard = self.wizard()
        wizard.action_generate()
        self.assertFalse(wizard.batch_id.slip_ids)
        self.assertIn('Contracts overlap', wizard.result)

    def test_failed_employee_rolls_back_only_its_drafts(self):
        second = self.employee.copy({'name': 'Second draft payroll employee'})
        self.contract.copy({'employee_id': second.id, 'state': 'open'})
        wizard = self.wizard(employee_ids=[(6, 0, (self.employee | second).ids)])
        original = type(wizard)._create_slip

        def fail_one(record, employee, *args):
            slip = original(record, employee, *args)
            if employee == self.employee:
                raise UserError('Test computation failure')
            return slip

        with patch.object(type(wizard), '_create_slip', fail_one):
            wizard.action_generate()
        self.assertEqual(wizard.batch_id.slip_ids.employee_id, second, wizard.result)
        self.assertFalse(self.env['hr.payslip'].search([('employee_id', '=', self.employee.id)]))
        self.assertIn('Test computation failure', wizard.result)

    def test_pending_review_and_withholding_follow_existing_payroll_rules(self):
        self.template.write({'overtime_enabled': True, 'weekly_off_overtime_policy': 'all'})
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': '2026-10-18 09:00:00', 'check_out': '2026-10-18 17:00:00'})
        sheet = self.env['bambus.hr.attendance.sheet'].search([
            ('company_id', '=', self.env.company.id), ('date', '=', '2026-10-18')], limit=1)
        sheet = sheet or self.env['bambus.hr.attendance.sheet'].create({'date': '2026-10-18'})
        self.env['bambus.hr.attendance.sheet.line'].create({
            'sheet_id': sheet.id, 'employee_id': self.employee.id, 'contract_id': self.contract.id,
            'overtime_state': 'submitted', 'overtime_hours': 8})
        wizard = self.wizard()
        wizard.action_generate()
        slip = wizard.batch_id.slip_ids
        self.assertEqual(slip.total_overtime_amount, 0)
        self.assertIn('Pending', wizard.result)
        before = slip.total_regular_pay_amount
        self.env['bambus.hr.attendance.sheet'].set_dashboard_paid_day(
            self.employee.id, '2026-10-18', 'weekly_off', 'withhold', 'Draft payroll test')
        wizard.action_recompute()
        self.assertAlmostEqual(slip.total_regular_pay_amount, before - 12000 / 31)
        self.assertEqual(slip.state, 'draft')

    def test_generation_does_not_inherit_payment_or_refund_defaults(self):
        wizard = self.wizard().with_context(default_state='done', default_credit_note=True, default_paid=True)
        wizard.action_generate()
        slip = wizard.batch_id.slip_ids
        self.assertEqual((wizard.batch_id.state, slip.state), ('draft', 'draft'))
        self.assertFalse(wizard.batch_id.credit_note or slip.credit_note or slip.paid)
