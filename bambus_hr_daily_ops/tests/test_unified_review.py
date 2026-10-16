from datetime import datetime

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestUnifiedAttendanceReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.day = fields.Date.to_date('2026-09-27')  # Sunday
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Review 8-hour calendar', 'tz': 'UTC',
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {'name': 'Work', 'dayofweek': str(day),
                'day_period': 'morning', 'hour_from': 9, 'hour_to': 17}) for day in range(5)],
        })
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Unified Review', 'weekly_off_source': 'weekdays', 'weekly_off_sunday': True,
            'weekly_off_overtime_policy': 'all', 'overtime_rate_policy': 'salary_multiplier',
            'overtime_calculation_type': 'salary_1_5', 'public_holiday_rate_policy': 'salary_multiplier',
            'public_holiday_calculation_type': 'salary_1_5', 'break_enabled': True,
        })
        cls.env['hr.salary.rule']._bambus_use_automation_amounts()
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Review Payroll', 'code': 'REVIEW_TEST', 'parent_id': False,
            'rule_ids': [(6, 0, [cls.env.ref(ref).id for ref in (
                'hr_payroll_community.hr_rule_basic', 'hr_payroll_community.hr_rule_taxable',
                'hr_payroll_community.hr_rule_net')])],
        })
        # PH is separate from OT and must reach payroll exactly once.
        cls.ph = cls.env['hr.salary.rule'].create({'name': 'Public Holiday', 'code': 'PH',
            'sequence': 35, 'category_id': cls.env.ref('hr_payroll_community.ALW').id,
            'condition_select': 'none', 'amount_select': 'code',
            'amount_python_compute': 'result = payslip.total_public_holiday_amount or 0.0'})
        cls.ot = cls.ph.copy({'name': 'Overtime', 'code': 'OT', 'sequence': 30,
            'amount_python_compute': 'result = payslip.total_overtime_amount or 0.0'})
        cls.fine = cls.ph.copy({'name': 'Fine', 'code': 'LATE', 'sequence': 40,
            'category_id': cls.env.ref('hr_payroll_community.DED').id,
            'amount_python_compute': 'result = -(payslip.total_fine_amount or 0.0)'})
        cls.structure.rule_ids |= cls.ph | cls.ot | cls.fine

    def worker(self, wage_type='monthly', day=None, attendance=True):
        day = day or self.day
        employee = self.env['hr.employee'].create({'name': 'Review ' + wage_type,
            'resource_calendar_id': self.calendar.id, 'attendance_automation_template_id': self.template.id})
        contract = self.env['hr.contract'].create({'name': 'Review Contract', 'employee_id': employee.id,
            'date_start': '2026-09-01', 'wage_type': wage_type, 'wage': 3000,
            'daily_wage': 100, 'hourly_rate': 12.5, 'resource_calendar_id': self.calendar.id,
            'struct_id': self.structure.id})
        if attendance:
            self.env['hr.attendance'].create({'employee_id': employee.id,
                'check_in': datetime.combine(day, datetime.min.time()).replace(hour=9),
                'check_out': datetime.combine(day, datetime.min.time()).replace(hour=17)})
        self.env['hr.attendance.overtime'].bambus_recompute_range(employee.ids, day, day)
        sheet = self.env['bambus.hr.attendance.sheet'].search([('date', '=', day)], limit=1)
        if not sheet:
            sheet = self.env['bambus.hr.attendance.sheet'].create({'date': day})
        line = self.env['bambus.hr.attendance.sheet.line'].create({'sheet_id': sheet.id,
            'employee_id': employee.id, 'contract_id': contract.id})
        line._compute_day_data()
        return employee, contract, line

    def wizard(self, line):
        return self.env['bambus.hr.attendance.review.wizard'].with_context(default_line_id=line.id).create({})

    def slip(self, employee, contract, day=None):
        day = day or self.day
        slip = self.env['hr.payslip'].create({'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id, 'date_from': day, 'date_to': day})
        slip.action_compute_sheet()
        return slip

    def test_daily_and_monthly_get_base_plus_only_approved_ot(self):
        for wage_type in ('daily', 'monthly'):
            with self.subTest(wage_type=wage_type):
                employee, contract, line = self.worker(wage_type)
                slip = self.slip(employee, contract)
                self.assertAlmostEqual(slip.total_regular_pay_amount, 100)
                self.assertEqual(slip.total_overtime_amount, 0)
                review = self.wizard(line)
                self.assertTrue(review.show_overtime)
                self.assertEqual(review.overtime_hours, 8)
                self.assertAlmostEqual(review.overtime_amount, 150)
                review.action_save()
                slip.action_compute_sheet()
                self.assertAlmostEqual(slip.line_ids.filtered(lambda row: row.code == 'BASIC').total, 100)
                self.assertAlmostEqual(slip.line_ids.filtered(lambda row: row.code == 'OT').total, 150)
                self.assertAlmostEqual(slip.line_ids.filtered(lambda row: row.code == 'NET').total, 250)

    def test_holiday_regular_pay_plus_approved_holiday_pay(self):
        day = fields.Date.to_date('2026-09-28')
        self.env['resource.calendar.leaves'].create({'name': 'Review Holiday', 'calendar_id': self.calendar.id,
            'date_from': '2026-09-28 00:00:00', 'date_to': '2026-09-28 23:59:59'})
        for kind in ('daily', 'monthly'):
            employee, contract, line = self.worker(kind, day=day)
            self.wizard(line).action_save()
            slip = self.slip(employee, contract, day)
            self.assertAlmostEqual(slip.total_public_holiday_amount, 150)
            self.assertEqual(slip.total_overtime_amount, 0)
            self.assertAlmostEqual(slip.line_ids.filtered(lambda row: row.code == 'NET').total, 250)

    def test_hourly_regular_pay_without_overtime(self):
        employee, contract, line = self.worker('hourly')
        self.assertFalse(self.wizard(line).show_overtime)
        # Even an old/manual approved OT must not pay an hourly employee twice.
        line.write({'overtime_state': 'approved', 'overtime_hours': 8, 'overtime_amount': 150})
        slip = self.slip(employee, contract)
        self.assertEqual(slip.total_overtime_amount, 0)
        self.assertEqual(slip.total_public_holiday_amount, 0)
        self.assertAlmostEqual(slip.total_regular_pay_amount, 100)
        self.assertAlmostEqual(slip.line_ids.filtered(lambda row: row.code == 'NET').total, 100)

    def test_unworked_monthly_weekly_off_paid_without_leave_record(self):
        for kind, expected in (('monthly', 100), ('daily', 0), ('hourly', 0)):
            employee, contract, line = self.worker(kind, attendance=False)
            slip = self.slip(employee, contract)
            self.assertEqual(slip.paid_weekly_off_days, 1 if kind == 'monthly' else 0)
            self.assertAlmostEqual(slip.total_regular_pay_amount, expected)
            self.assertAlmostEqual(slip.line_ids.filtered(lambda row: row.code == 'NET').total, expected)
            self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', employee.id)]))
            if kind == 'monthly':
                worked = slip.get_worked_day_lines(contract, self.day, self.day)
                self.assertEqual(next(row['number_of_days'] for row in worked if row['code'] == 'PAID_WEEKLY_OFF'), 1)

    def test_ignore_overtime_is_permanent_and_keeps_regular_pay(self):
        employee, contract, line = self.worker('daily')
        wizard = self.wizard(line)
        wizard.ignore_overtime = True
        wizard.action_save()
        line.action_refresh()
        self.assertEqual(line.overtime_state, 'rejected')
        self.assertFalse(self.wizard(line).show_overtime)
        slip = self.slip(employee, contract)
        self.assertEqual(slip.total_overtime_amount, 0)
        self.assertAlmostEqual(slip.total_regular_pay_amount, 100)

    def test_one_review_approves_ot_and_fines_and_persists_deleted_break(self):
        day = fields.Date.to_date('2026-09-28')
        employee, contract, line = self.worker('monthly', day=day)
        # Separate morning late arrival, an internal gap, and after-shift OT.
        self.template.write({'full_day_basis': 'schedule'})
        attendance = line._review_attendances()
        attendance.unlink()
        self.env['hr.attendance'].create([
            {'employee_id': employee.id, 'check_in': '2026-09-28 10:00:00', 'check_out': '2026-09-28 11:00:00'},
            {'employee_id': employee.id, 'check_in': '2026-09-28 14:00:00', 'check_out': '2026-09-28 15:00:00'},
        ])
        line.action_refresh()
        # HR may also propose OT manually while reviewing detected fines.
        line.write({'overtime_hours': 1, 'overtime_state': 'submitted'})
        wizard = self.wizard(line)
        kinds = set(wizard.fine_line_ids.mapped('kind'))
        self.assertTrue({'late', 'break'} <= kinds, kinds)
        self.assertTrue(wizard.show_overtime)
        late = wizard.fine_line_ids.filtered(lambda row: row.kind == 'late')
        expected_amount = sum((wizard.fine_line_ids - wizard.fine_line_ids.filtered(lambda row: row.kind == 'break')).mapped('amount'))
        wizard.fine_line_ids.filtered(lambda row: row.kind == 'break').unlink()
        wizard.action_save()
        self.assertEqual(line.fine_review_data['break']['state'], 'ignored')
        self.assertEqual(line.overtime_state, 'approved')
        self.assertAlmostEqual(line.fine_amount, expected_amount)
        line.action_refresh()
        reopened = self.wizard(line)
        self.assertNotIn('break', reopened.fine_line_ids.mapped('kind'))
        self.assertAlmostEqual(line.fine_amount, expected_amount)
        reopened.fine_line_ids.unlink()
        reopened.action_save()
        self.assertEqual(line.fine_state, 'rejected')
        self.assertEqual(self.slip(employee, contract, day).total_fine_amount, 0)

    def test_stale_review_and_invalid_hours_cannot_approve(self):
        employee, contract, line = self.worker()
        wizard = self.wizard(line)
        wizard.source_write_date = fields.Datetime.to_datetime('2000-01-01')
        with self.assertRaises(UserError):
            wizard.action_save()
        dashboard = self.env['bambus.hr.attendance.sheet']
        payload = dashboard.get_dashboard_review(employee.id, self.day)
        for invalid in (-1, float('nan'), float('inf')):
            with self.assertRaises(UserError):
                dashboard.save_dashboard_review(payload['wizard_id'], [{**payload['items'][0], 'hours': invalid}])

    def test_dashboard_delete_all_items_remains_excluded_after_recompute(self):
        employee, contract, line = self.worker('monthly')
        dashboard = self.env['bambus.hr.attendance.sheet']
        payload = dashboard.get_dashboard_review(employee.id, self.day)
        self.assertEqual([item['id'] for item in payload['items']], ['overtime'])
        dashboard.save_dashboard_review(payload['wizard_id'], [])
        self.env['hr.attendance.overtime'].bambus_recompute_range(employee.ids, self.day, self.day)
        line.action_refresh()
        self.assertEqual(dashboard.get_dashboard_review(employee.id, self.day)['items'], [])
        self.assertEqual(self.slip(employee, contract).total_overtime_amount, 0)

    def test_review_disallows_non_hr_and_other_company(self):
        employee, contract, line = self.worker('monthly')
        user = self.env['res.users'].create({'name': 'Review Non HR', 'login': 'review_non_hr',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(UserError):
            line.with_user(user).action_review_adjustments()
        other = self.env['res.company'].create({'name': 'Review Other Company'})
        self.env.user.company_ids |= other
        with self.assertRaises(UserError):
            line.with_context(allowed_company_ids=[other.id]).action_review_adjustments()

    def test_paid_weekly_off_respects_contract_boundary_and_holiday_precedence(self):
        employee, contract, line = self.worker('monthly', attendance=False)
        contract.date_start = '2026-09-28'
        self.assertEqual(self.slip(employee, contract).paid_weekly_off_days, 0)
        contract.date_start = '2026-09-01'
        self.env['resource.calendar.leaves'].create({'name': 'Sunday Holiday', 'calendar_id': self.calendar.id,
            'date_from': '2026-09-27 00:00:00', 'date_to': '2026-09-27 23:59:59'})
        self.assertEqual(self.slip(employee, contract).paid_weekly_off_days, 0)

    def test_paid_leave_remains_in_regular_pay(self):
        day = fields.Date.to_date('2026-09-28')
        employee, contract, line = self.worker('monthly', day=day, attendance=False)
        leave_type = self.env['hr.leave.type'].create({'name': 'Review Paid Leave', 'requires_allocation': 'no'})
        leave = self.env['hr.leave'].create({'employee_id': employee.id, 'holiday_status_id': leave_type.id,
            'request_date_from': day, 'request_date_to': day})
        leave.action_approve()
        if leave.state != 'validate':
            leave.action_validate()
        self.assertEqual(self.slip(employee, contract, day).total_regular_pay_amount, 100)

    def test_splitting_fixed_fine_preserves_total_including_rounding(self):
        day = fields.Date.to_date('2026-09-28')
        self.template.write({'fine_calculation_type': 'fixed', 'fine_rate': 100})
        employee, contract, line = self.worker('monthly', day=day, attendance=False)
        self.env['hr.attendance'].create([
            {'employee_id': employee.id, 'check_in': '2026-09-28 10:00:00', 'check_out': '2026-09-28 11:00:00'},
            {'employee_id': employee.id, 'check_in': '2026-09-28 14:00:00', 'check_out': '2026-09-28 15:00:00'},
        ])
        line.action_refresh()
        wizard = self.wizard(line)
        self.assertEqual(len(wizard.fine_line_ids), 3)
        self.assertAlmostEqual(sum(wizard.fine_line_ids.mapped('amount')), 100)
        wizard.action_save()
        self.assertAlmostEqual(line.fine_amount, 100)

    def test_monthly_paid_weekly_off_switch_refreshes_pay_and_worked_days(self):
        employee, contract, line = self.worker('monthly', attendance=False)
        slip = self.slip(employee, contract)
        self.assertTrue(self.template.monthly_paid_weekly_off)
        self.assertEqual((slip.paid_weekly_off_days, slip.total_regular_pay_amount), (1, 100))
        self.template.monthly_paid_weekly_off = False
        self.assertEqual((slip.paid_weekly_off_days, slip.paid_weekly_off_amount,
                          slip.total_regular_pay_amount), (0, 0, 0))
        slip.action_compute_sheet()
        self.assertNotIn('PAID_WEEKLY_OFF', slip.worked_days_line_ids.mapped('code'))
        self.template.monthly_paid_weekly_off = True
        self.assertEqual((slip.paid_weekly_off_days, slip.total_regular_pay_amount), (1, 100))

    def test_paid_weekly_off_uses_effective_employee_then_company_template(self):
        employee, contract, line = self.worker('monthly', attendance=False)
        company_template = self.template.copy({'name': 'Company Paid Off', 'monthly_paid_weekly_off': True})
        employee.company_id.attendance_automation_template_id = company_template
        self.template.monthly_paid_weekly_off = False
        slip = self.slip(employee, contract)
        self.assertEqual(slip.paid_weekly_off_days, 0)
        self.template.date_from = '2026-09-28'
        self.assertEqual(slip.paid_weekly_off_days, 1)
        company_template.monthly_paid_weekly_off = False
        self.assertEqual(slip.paid_weekly_off_days, 0)
        company_template.active = False
        self.assertEqual(slip.paid_weekly_off_days, 1)  # Legacy fallback.

    def test_review_displays_actual_contract_wage_for_each_basis(self):
        for basis, label, field, value in [('monthly', 'Monthly Wage', 'wage', 9000),
                                          ('daily', 'Daily Wage', 'daily_wage', 750),
                                          ('hourly', 'Hourly Rate', 'hourly_rate', 125)]:
            with self.subTest(basis=basis):
                employee, contract, line = self.worker(basis)
                contract[field] = value
                wizard = self.wizard(line)
                self.assertEqual((wizard.contract_wage_label, wizard.contract_wage_amount), (label, value))
                payload = self.env['bambus.hr.attendance.sheet'].get_dashboard_review(employee.id, self.day)
                self.assertEqual((payload['contract_wage_label'], payload['contract_wage_amount']), (label, value))

    def test_disabling_unworked_credit_preserves_worked_base_and_approved_ot(self):
        self.template.monthly_paid_weekly_off = False
        employee, contract, line = self.worker('monthly')
        self.wizard(line).action_save()
        slip = self.slip(employee, contract)
        self.assertEqual(slip.paid_weekly_off_days, 0)
        self.assertEqual((slip.total_regular_pay_amount, slip.total_overtime_amount), (100, 150))

    def test_hourly_pay_review_displays_contract_hourly_rate(self):
        self.template.hourly_pay_enabled = True
        employee, contract, line = self.worker('hourly')
        payload = self.env['bambus.hr.attendance.sheet'].get_dashboard_adjustment(employee.id, self.day, 'hourly_pay')
        self.assertEqual((payload['contract_wage_label'], payload['contract_wage_amount']), ('Hourly Rate', 12.5))
