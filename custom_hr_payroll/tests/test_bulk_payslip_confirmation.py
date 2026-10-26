from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user


class TestBulkPayslipConfirmation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.basic = cls.env['hr.salary.rule'].create({'name': 'Bulk basic', 'code': 'BASIC',
            'sequence': 10, 'category_id': cls.env.ref('hr_payroll_community.BASIC').id,
            'condition_select': 'none', 'amount_select': 'fix', 'amount_fix': 1000})
        net = cls.env['hr.salary.rule'].create({'name': 'Bulk net', 'code': 'NET',
            'sequence': 20, 'category_id': cls.env.ref('hr_payroll_community.NET').id,
            'condition_select': 'none', 'amount_select': 'code', 'amount_python_compute': 'result = categories.BASIC'})
        cls.structure = cls.env['hr.payroll.structure'].create({'name': 'Bulk confirmation payroll',
            'code': 'BULK_CONFIRM_TEST', 'parent_id': False, 'rule_ids': [(6, 0, (cls.basic | net).ids)]})

    def slips(self, computed=True):
        result = self.env['hr.payslip']
        for basis in ('monthly', 'daily', 'hourly'):
            employee = self.env['hr.employee'].create({'name': 'Bulk ' + basis})
            contract = self.env['hr.contract'].create({'name': 'Bulk ' + basis,
                'employee_id': employee.id, 'date_start': '2026-10-01', 'wage_type': basis,
                'wage': 8000, 'daily_wage': 885, 'hourly_rate': 53, 'struct_id': self.structure.id})
            result |= self.env['hr.payslip'].create({'employee_id': employee.id,
                'contract_id': contract.id, 'struct_id': self.structure.id,
                'date_from': '2026-10-01', 'date_to': '2026-10-31'})
        if computed:
            result.action_compute_sheet()
        return result

    def wizard(self, slips):
        action = slips.action_open_bulk_confirmation()
        return self.env[action['res_model']].browse(action['res_id'])

    def test_confirm_three_wage_types_and_done_report_without_payment(self):
        slips = self.slips()
        wizard = self.wizard(slips)
        self.assertEqual((wizard.slip_count, wizard.total_net), (3, 3000))
        self.assertEqual(set(slips.mapped('state')), {'draft'})  # Opening/Cancel changes nothing.
        slips[1].state = 'verify'
        wizard.action_confirm()
        self.assertEqual(set(slips.mapped('state')), {'done'})
        self.assertFalse(any(slips.mapped('paid')))
        self.assertEqual(sum(slips.line_ids.filtered(lambda line: line.code == 'NET').mapped('total')), 3000)
        if 'payslip.excel.wizard' in self.env:
            report = self.env['payslip.excel.wizard'].create({'duration_type': 'custom',
                'start_date': '2026-10-01', 'end_date': '2026-10-31',
                'employee_ids': [(6, 0, slips.employee_id.ids)]})
            self.assertFalse(report._selected_payslips())
            report.payslip_status = 'done'
            self.assertEqual(report._selected_payslips(), slips)
            self.assertTrue(report._generate_xlsx().startswith(b'PK'))

    def test_stale_salary_rolls_back_all_and_keeps_saved_salary(self):
        slips = self.slips()
        saved = [(line.id, line.total) for line in slips.line_ids]
        wizard = self.wizard(slips)
        self.basic.amount_fix = 2000
        with self.assertRaisesRegex(UserError, 'Salary changed'):
            wizard.action_confirm()
        self.assertEqual(set(slips.mapped('state')), {'draft'})
        self.assertEqual([(line.id, line.total) for line in slips.line_ids], saved)

    def test_second_standard_confirmation_failure_rolls_back_first(self):
        slips = self.slips()
        saved = [(line.id, line.total) for line in slips.line_ids]
        original = type(slips).action_payslip_done
        calls = []
        def confirm(record):
            calls.append(record.id)
            if len(calls) == 2:
                raise UserError('Accounting validation failed')
            return original(record)
        with patch.object(type(slips), 'action_payslip_done', confirm):
            with self.assertRaisesRegex(UserError, 'Accounting validation failed'):
                self.wizard(slips).action_confirm()
        self.assertEqual(calls, slips[:2].ids)
        self.assertEqual(set(slips.mapped('state')), {'draft'})
        self.assertEqual([(line.id, line.total) for line in slips.line_ids], saved)

    def test_reject_uncomputed_done_cancelled_and_empty_selection(self):
        slips = self.slips(computed=False)
        with self.assertRaisesRegex(UserError, 'Compute and review'):
            self.wizard(slips)
        slips.action_compute_sheet()
        for state in ('done', 'cancel'):
            slips[0].state = state
            with self.assertRaisesRegex(UserError, 'Select only Draft'):
                self.wizard(slips)
        with self.assertRaisesRegex(UserError, 'Select the payslips'):
            self.wizard(self.env['hr.payslip'])

    def test_recheck_state_on_confirm_and_deny_unprivileged_rpc(self):
        slips = self.slips()
        wizard = self.wizard(slips)
        slips[0].state = 'done'
        with self.assertRaisesRegex(UserError, 'Select only Draft'):
            wizard.action_confirm()
        user = new_test_user(self.env, login='bulk_confirm_no_access', groups='base.group_user')
        with self.assertRaises(AccessError):
            slips.with_user(user).action_open_bulk_confirmation()

    def test_list_action_is_bound_and_rejects_mixed_companies(self):
        action = self.env.ref('custom_hr_payroll.action_bulk_confirm_payslips')
        self.assertEqual((action.binding_model_id.model, action.binding_view_types), ('hr.payslip', 'list'))
        slips = self.slips()
        company = self.env['res.company'].create({'name': 'Other bulk payroll company'})
        employee = self.env['hr.employee'].create({'name': 'Other bulk worker', 'company_id': company.id})
        other = self.env['hr.payslip'].create({'employee_id': employee.id, 'company_id': company.id,
            'date_from': '2026-10-01', 'date_to': '2026-10-31'})
        with self.assertRaisesRegex(UserError, 'one enabled company'):
            self.wizard(slips | other)
