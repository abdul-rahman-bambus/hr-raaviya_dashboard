"""Paid-day exceptions must agree across dashboard, payroll and reports."""
from datetime import datetime

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestPaidDayWithholding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Withholding calendar', 'tz': 'UTC', 'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                        'hour_from': 9, 'hour_to': 17}) for day in range(6)],
        })
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Withholding rules', 'weekly_off_source': 'weekdays',
            'weekly_off_sunday': True, 'monthly_paid_weekly_off': True,
            'monthly_paid_public_holiday': True, 'full_day_basis': 'fixed',
            'full_day_hours': 8, 'half_day_hours': 4, 'weekly_off_overtime_policy': 'all',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Withholding employee', 'resource_calendar_id': cls.calendar.id,
            'attendance_automation_template_id': cls.template.id,
        })
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Withholding contract', 'employee_id': cls.employee.id,
            'date_start': '2026-10-01', 'date_end': '2026-10-31',
            'wage_type': 'monthly', 'wage': 12000, 'resource_calendar_id': cls.calendar.id,
        })
        cls.env['resource.calendar.leaves'].create({
            'name': 'Withholding holiday', 'calendar_id': cls.calendar.id,
            'date_from': '2026-10-19 00:00:00', 'date_to': '2026-10-19 23:59:59',
        })
        cls.sheet_model = cls.env['bambus.hr.attendance.sheet']
        cls.officer = new_test_user(cls.env, login='paid_day_hr', groups='hr.group_hr_user,hr_contract.group_hr_contract_manager')
        cls.basic_user = new_test_user(cls.env, login='paid_day_basic', groups='base.group_user')

    def decide(self, day='2026-10-18', kind='weekly_off', action='withhold', reason='HR exception'):
        return self.sheet_model.with_user(self.officer).set_dashboard_paid_day(
            self.employee.id, day, kind, action, reason)

    def row(self, day):
        return next(row for row in self.sheet_model.get_attendance_dashboard(day)['daily_attendance']
                    if row['id'] == self.employee.id)

    def slip(self):
        return self.env['hr.payslip'].create({
            'employee_id': self.employee.id, 'contract_id': self.contract.id,
            'date_from': '2026-10-18', 'date_to': '2026-10-19',
        })

    def test_unworked_days_withhold_restore_payroll_report_and_audit(self):
        slip = self.slip()
        self.assertAlmostEqual(slip.total_regular_pay_amount, 2 * 12000 / 31)
        for day, kind in [('2026-10-18', 'weekly_off'), ('2026-10-19', 'public_holiday')]:
            self.assertEqual(self.row(day)['status'], 'paid_' + kind)
            self.decide(day, kind)
            row = self.row(day)
            self.assertEqual(row['status'], 'unpaid_' + kind)
            self.assertTrue(row['paid_day_withheld'])
            self.assertEqual(row['paid_day_reason'], 'HR exception')
            self.assertFalse(row['has_attendance'])
            self.assertTrue(any(log['label'] == 'Paid-off Credit Withheld' for log in row['logs']))
        # Stored totals react to the audit relation; draft computation refreshes rows.
        self.assertEqual(slip.total_regular_pay_amount, 0)
        slip.action_compute_sheet()
        self.assertEqual((slip.paid_weekly_off_days, slip.paid_public_holiday_days), (0, 0))
        self.assertFalse(slip.worked_days_line_ids.filtered(lambda line: line.code.startswith('PAID_')))
        if 'report.attendance_custom_report.attendance_xlsx' in self.env:
            wizard = self.env['attendance.report.wizard'].create({
                'date_start': '2026-10-18', 'date_end': '2026-10-19',
                'employee_ids': [(6, 0, self.employee.ids)], 'report_type': 'monthly'})
            report = self.env['report.attendance_custom_report.attendance_xlsx']
            totals = report._totals_for_emp(self.employee, wizard)
            self.assertEqual((totals['paid_weekly_off_days'], totals['paid_public_holiday_days']), (0, 0))
        self.decide(action='restore', reason='Credit reinstated')
        self.assertEqual(self.row('2026-10-18')['status'], 'paid_weekly_off')
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000 / 31)
        decisions = self.employee._get_paid_day_decision('2026-10-18', 'weekly_off')
        self.assertEqual(decisions.actor_id, self.officer)
        history = self.env['bambus.attendance.paid.day.decision'].search([
            ('employee_id', '=', self.employee.id), ('date', '=', '2026-10-18')])
        self.assertEqual(len(history), 2)
        self.assertEqual(set(history.mapped('action')), {'withhold', 'restore'})
        self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', self.employee.id)]))

    def test_worked_day_keeps_punches_and_approved_ot_fine(self):
        attendance = self.env['hr.attendance'].create({
            'employee_id': self.employee.id, 'check_in': datetime(2026, 10, 18, 9),
            'check_out': datetime(2026, 10, 18, 17),
        })
        sheet = self.sheet_model.search([('date', '=', '2026-10-18'),
                                        ('company_id', '=', self.env.company.id)], limit=1)
        sheet = sheet or self.sheet_model.create({'date': '2026-10-18'})
        line = self.env['bambus.hr.attendance.sheet.line'].create({
            'sheet_id': sheet.id, 'employee_id': self.employee.id, 'contract_id': self.contract.id,
            'overtime_state': 'approved', 'overtime_hours': 8, 'overtime_amount': 250,
            'fine_state': 'approved', 'fine_hours': 0.1, 'fine_amount': 10,
        })
        slip = self.slip()
        self.decide()
        row = self.row('2026-10-18')
        self.assertEqual(row['status'], 'present')
        self.assertTrue(row['paid_day_withheld'])
        self.assertEqual(attendance.worked_hours, 8)
        slip.action_compute_sheet()
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000 / 31)  # Monday only
        self.assertEqual((slip.total_overtime_amount, slip.total_fine_amount), (250, 10))
        self.assertEqual((line.overtime_amount, line.fine_amount), (250, 10))
        self.assertEqual(slip.weekend_worked, 1)
        self.assertEqual(slip.withheld_weekly_off_worked_days, 1)
        weekend = slip.worked_days_line_ids.filtered(lambda row: row.code == 'WEEKEND')
        self.assertEqual((weekend.number_of_days, weekend.number_of_hours), (0, 8))
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 1)
        # Detection/recalculation must not undo the decision.
        self.env['hr.attendance.overtime'].bambus_recompute_range(
            self.employee.ids, fields.Date.to_date('2026-10-18'), fields.Date.to_date('2026-10-19'))
        self.assertTrue(self.employee._is_paid_day_withheld('2026-10-18', 'weekly_off'))
        self.decide(action='restore')
        slip.action_compute_sheet()
        self.assertAlmostEqual(slip.total_regular_pay_amount, 2 * 12000 / 31)
        self.assertEqual(slip.withheld_weekly_off_worked_days, 0)
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 2)

    def test_worked_withheld_holiday_has_hours_but_no_paid_day(self):
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': '2026-10-19 09:00:00', 'check_out': '2026-10-19 17:00:00'})
        self.decide('2026-10-19', 'public_holiday')
        slip = self.slip()
        slip.action_compute_sheet()
        holiday = slip.worked_days_line_ids.filtered(lambda row: row.code == 'HOLIDAYS')
        self.assertEqual((holiday.number_of_days, holiday.number_of_hours), (0, 8))
        self.assertEqual((slip.holiday_worked, slip.withheld_public_holiday_worked_days), (1, 1))
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 1)
        self.decide('2026-10-19', 'public_holiday', 'restore')
        slip.action_compute_sheet()
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 2)

    def test_withheld_work_without_ot_policy_does_not_fall_back_to_calendar_days(self):
        self.template.write({'overtime_enabled': False, 'weekly_off_overtime_policy': 'disabled',
                             'monthly_paid_public_holiday': False})
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': '2026-10-18 09:00:00', 'check_out': '2026-10-18 17:00:00'})
        self.decide()
        slip = self.slip()
        slip.action_compute_sheet()
        self.assertEqual(slip.total_regular_pay_amount, 0)
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 0)
        self.assertEqual(slip.weekend_worked, 1)

    def test_restore_obeys_current_template_overlap_and_contract(self):
        self.template.weekly_off_monday = True
        with self.assertRaises(UserError):
            self.decide('2026-10-19', 'weekly_off')
        self.decide('2026-10-19', 'public_holiday')
        self.template.monthly_paid_public_holiday = False
        self.decide('2026-10-19', 'public_holiday', 'restore')
        self.assertEqual(self.row('2026-10-19')['status'], 'not_marked')
        self.assertFalse(self.employee._is_paid_attendance_public_holiday('2026-10-19', self.contract))
        for day in ['2026-10-20', '2026-11-01']:
            with self.assertRaises(UserError):
                self.decide(day)
        for basis in ['daily', 'hourly']:
            self.contract.wage_type = basis
            with self.assertRaises(UserError):
                self.decide()

    def test_reason_permissions_company_scope_and_append_only_history(self):
        with self.assertRaises(ValidationError):
            self.decide(reason='   ')
        with self.assertRaises(UserError):
            self.sheet_model.with_user(self.basic_user).set_dashboard_paid_day(
                self.employee.id, '2026-10-18', 'weekly_off', 'withhold', 'Not HR')
        company = self.env['res.company'].create({'name': 'Other withholding company'})
        other = self.env['hr.employee'].create({'name': 'Other employee', 'company_id': company.id})
        with self.assertRaises(AccessError):
            self.sheet_model.with_user(self.officer).set_dashboard_paid_day(
                other.id, '2026-10-18', 'weekly_off', 'withhold', 'Wrong company')
        self.decide()
        decision = self.employee._get_paid_day_decision('2026-10-18', 'weekly_off').with_user(self.officer)
        with self.assertRaises(AccessError):
            decision.write({'reason': 'Tamper'})
        with self.assertRaises(AccessError):
            decision.unlink()
        with self.assertRaises(AccessError):
            self.env['bambus.attendance.paid.day.decision'].with_user(self.officer).create({
                'employee_id': self.employee.id, 'date': '2026-10-20', 'kind': 'weekly_off',
                'action': 'restore', 'reason': 'Bypass', 'actor_id': self.officer.id})
        with self.assertRaises(UserError):
            self.decide()

    def test_withholding_does_not_rewrite_finalized_salary_lines(self):
        self.env['hr.salary.rule']._bambus_use_automation_amounts()
        structure = self.env['hr.payroll.structure'].create({
            'name': 'Withholding salary structure', 'code': 'WITHHOLD_TEST', 'parent_id': False,
            'rule_ids': [(6, 0, [self.env.ref('hr_payroll_community.hr_rule_basic').id,
                                self.env.ref('hr_payroll_community.hr_rule_net').id])],
        })
        slip = self.slip()
        slip.struct_id = structure
        slip.action_compute_sheet()
        basic = slip.line_ids.filtered(lambda line: line.code == 'BASIC')
        self.assertAlmostEqual(basic.total, 2 * 12000 / 31, places=2)
        saved = [(line.id, line.total) for line in slip.line_ids]
        slip.state = 'done'
        self.decide()
        self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
        self.decide(action='restore')
        self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
