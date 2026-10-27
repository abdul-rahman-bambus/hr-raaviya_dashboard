from types import SimpleNamespace

from odoo import fields
from odoo.tests.common import TransactionCase

from . import test_unified_review


class TestPartialSalaryTreatment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.day = fields.Date.to_date('2026-10-22')
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Fine-only 8:15 schedule', 'tz': 'UTC',
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'name': period, 'dayofweek': str(day), 'day_period': period,
                'hour_from': start, 'hour_to': end}) for day in range(7)
                for period, start, end in [('morning', 9.75, 14), ('afternoon', 14.75, 18.75)]]})
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Normal day minus approved fines', 'partial_attendance_salary_treatment': 'fine_only',
            'weekly_off_source': 'weekdays', 'full_day_basis': 'schedule', 'half_day_hours': 4,
            'late_enabled': True, 'late_grace_minutes': 5, 'early_exit_enabled': True,
            'early_exit_grace_minutes': 0, 'post_break_grace_minutes': 0,
            'fine_calculation_type': 'salary_minute', 'break_enabled': True, 'allowed_break_minutes': 0})
        cls.env['hr.salary.rule']._bambus_use_automation_amounts()
        cls.fine_rule = cls.env['hr.salary.rule'].create({
            'name': 'Approved fine', 'code': 'LF', 'sequence': 40,
            'category_id': cls.env.ref('hr_payroll_community.DED').id,
            'condition_select': 'none', 'amount_select': 'code',
            'amount_python_compute': 'result = -(payslip.total_fine_amount or 0.0)'})
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Fine-only payroll', 'code': 'PARTIAL_FINE_ONLY', 'parent_id': False,
            'rule_ids': [(6, 0, [cls.env.ref('hr_payroll_community.' + key).id for key in
                ('hr_rule_basic', 'hr_rule_taxable', 'hr_rule_net')] + cls.fine_rule.ids)]})

    wizard = test_unified_review.TestUnifiedAttendanceReview.wizard

    def person(self, basis='daily', spans=None, day=None):
        day = day or self.day
        employee, contract, line = test_unified_review.TestUnifiedAttendanceReview.worker(self, basis, day, attendance=False)
        contract.write({'wage': 8000, 'daily_wage': 885, 'hourly_rate': 53})
        for start, end in (spans if spans is not None else [('09:45', '12:00')]):
            self.env['hr.attendance'].create({'employee_id': employee.id,
                'check_in': str(day) + ' ' + start + ':00',
                'check_out': str(day) + ' ' + end + ':00' if end else False})
        line.action_refresh()
        return employee, contract, line

    def slip(self, employee, contract, start=None, end=None):
        slip = self.env['hr.payslip'].create({'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id, 'date_from': start or self.day, 'date_to': end or start or self.day})
        slip.action_compute_sheet()
        return slip

    def net(self, slip):
        return slip.line_ids.filtered(lambda row: row.code == 'NET').total

    def test_daily_two_hours_fifteen_gets_day_pay_minus_only_approved_six_hour_fine(self):
        employee, contract, line = self.person()
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_regular_pay_amount, slip.total_working_days, self.net(slip)), (885, 1, 885))
        self.assertEqual(slip.total_fine_amount, 0)
        review = self.wizard(line)
        self.assertEqual(review.fine_line_ids.mapped('kind'), ['early'])
        self.assertEqual(review.fine_line_ids.hours, 6)
        review.action_save()
        slip.action_compute_sheet()
        self.assertEqual((slip.total_regular_pay_amount, slip.total_fine_amount, self.net(slip)), (885, 643.64, 241.36))
        self.assertEqual(slip.worked_days_line_ids.filtered(lambda row: row.code == 'DAYSWORKED').number_of_days, 1)
        self.assertEqual(slip.worked_days_line_ids.filtered(lambda row: row.code == 'DAYSWORKED').number_of_hours, 2.25)
        self.assertEqual(sum(line._review_attendances().mapped('worked_hours')), 2.25)
        self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', employee.id)]))
        detail = slip.attendance_deduction_detail_ids
        self.assertEqual((detail.hours, detail.amount, detail.rate_unit), (6, 643.64, 'per minute'))

    def test_monthly_uses_calendar_month_day_rate_without_half_day_cut(self):
        employee, contract, line = self.person('monthly')
        self.wizard(line).action_save()
        slip = self.slip(employee, contract)
        self.assertAlmostEqual(slip.total_regular_pay_amount, 8000 / 31)
        self.assertEqual(slip.total_fine_amount, 187.68)
        self.assertEqual(self.net(slip), 70.38)
        self.assertEqual(slip.total_working_days, 1)

    def test_dashboard_exposes_whole_day_fine_and_saved_review(self):
        employee, contract, line = self.person()
        def dashboard_row():
            data = self.env['bambus.attendance.dashboard'].get_attendance_dashboard(str(self.day))
            return next(row for row in data['daily_attendance'] if row['id'] == employee.id)
        row = dashboard_row()
        self.assertEqual(row['fine_hours'], 6)
        self.assertTrue(row['fine_review_pending'])
        review = self.wizard(line)
        review.fine_line_ids.hours = 3
        review.action_save()
        row = dashboard_row()
        self.assertEqual(row['fine_hours'], 3)
        self.assertFalse(row['fine_review_pending'])

    def test_ignored_fine_keeps_day_pay_and_cancel_does_not_save(self):
        employee, contract, line = self.person()
        review = self.wizard(line)
        review.fine_line_ids.unlink()
        self.assertNotEqual(line.fine_state, 'rejected')
        self.assertEqual(self.net(self.slip(employee, contract)), 885)
        review.action_save()
        line.action_refresh()
        self.assertEqual(line.fine_state, 'rejected')
        self.assertFalse(self.wizard(line).fine_line_ids)
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_fine_amount, self.net(slip)), (0, 885))

    def test_hr_changes_minutes_and_calculation_without_changing_day_pay(self):
        employee, contract, line = self.person()
        review = self.wizard(line)
        review.fine_line_ids.write({'hours': 1, 'calculation_type': 'fixed_hour', 'rate': 50})
        review.action_save()
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_regular_pay_amount, slip.total_fine_amount, self.net(slip)), (885, 50, 835))
        self.assertEqual(sum(line._review_attendances().mapped('worked_hours')), 2.25)

    def test_threshold_mode_keeps_existing_day_fractions(self):
        self.template.write({'partial_attendance_salary_treatment': 'thresholds', 'reviewed_exception_day_pay': 'actual'})
        for spans, expected in [([('09:45', '12:00')], 0), ([('09:45', '14:00')], .5),
                                ([('09:45', '14:00'), ('14:45', '18:45')], 1)]:
            employee, contract, line = self.person(spans=spans)
            slip = self.slip(employee, contract)
            self.assertEqual(slip.total_working_days, expected)
            self.assertEqual(slip.total_regular_pay_amount, 885 * expected)
        template = self.env['bambus.attendance.automation.template'].create({'name': 'Existing default'})
        self.assertEqual(template.partial_attendance_salary_treatment, 'thresholds')

    def test_missing_afternoon_is_fined_even_above_half_day_threshold(self):
        employee, contract, line = self.person(spans=[('09:45', '14:00')])
        review = self.wizard(line)
        self.assertEqual(review.fine_line_ids.hours, 4)
        review.action_save()
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_working_days, slip.total_regular_pay_amount, self.net(slip)), (1, 885, 455.91))

    def test_missing_morning_is_late_time_with_configured_grace(self):
        employee, contract, line = self.person(spans=[('14:45', '18:45')])
        review = self.wizard(line)
        self.assertEqual(review.fine_line_ids.mapped('kind'), ['late'])
        self.assertAlmostEqual(review.fine_line_ids.hours, 250 / 60, places=6)
        self.assertEqual(self.slip(employee, contract).total_regular_pay_amount, 885)

    def test_absent_open_zero_and_outside_schedule_do_not_grant_day_pay(self):
        for spans in ([], [('09:45', None)], [('09:45', '09:45')], [('19:00', '20:00')]):
            employee, contract, line = self.person(spans=spans)
            slip = self.slip(employee, contract)
            self.assertEqual(slip.total_regular_pay_amount, 0)
            self.assertEqual(slip.total_fine_amount, 0)
            self.assertFalse(self.wizard(line).fine_line_ids)

    def test_hourly_stays_actual_payable_hours(self):
        employee, contract, line = self.person('hourly')
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_regular_pay_amount, self.net(slip)), (119.25, 119.25))
        self.assertEqual(slip.total_worker_days, 1)
        self.assertFalse(self.wizard(line).fine_line_ids)

    def test_company_fallback_and_effective_contract_boundaries(self):
        employee, contract, line = self.person()
        company = self.template.copy({'name': 'Company fine-only'})
        self.env.company.attendance_automation_template_id = company
        self.template.date_from = '2026-11-01'
        self.assertEqual(self.slip(employee, contract).total_regular_pay_amount, 885)
        company.partial_attendance_salary_treatment = 'thresholds'
        self.assertEqual(self.slip(employee, contract).total_regular_pay_amount, 0)
        contract.date_start = '2026-11-01'
        company.partial_attendance_salary_treatment = 'fine_only'
        self.assertEqual(self.slip(employee, contract).total_regular_pay_amount, 0)

    def test_mode_change_recomputes_draft_but_not_finalized_salary(self):
        employee, contract, line = self.person()
        self.wizard(line).action_save()
        slip = self.slip(employee, contract)
        self.assertEqual(self.net(slip), 241.36)
        salary = [(row.id, row.total) for row in slip.line_ids]
        details = slip.attendance_detail_ids.ids
        slip.state = 'done'
        self.template.partial_attendance_salary_treatment = 'thresholds'
        slip.action_compute_sheet()
        self.assertEqual([(row.id, row.total) for row in slip.line_ids], salary)
        self.assertEqual(slip.attendance_detail_ids.ids, details)

    def test_reports_count_attended_date_once_and_keep_real_hours(self):
        if 'report.hr_payslip_excel_report.payroll_review' not in self.env:
            self.skipTest('Payroll XLSX module is not installed')
        employee, contract, line = self.person()
        self.wizard(line).action_save()
        slip = self.slip(employee, contract)
        daily = self.env['report.attendance_custom_report.attendance_xlsx']._compute_employee_daily(
            employee, SimpleNamespace(date_start=self.day, date_end=self.day), contract=contract)[self.day]
        self.assertEqual((daily['day_fraction'], daily['worked'], daily['regularized_hours']), (1, 2.25, 0))
        wizard = self.env['payslip.excel.wizard'].create({'report_type': 'summary', 'duration_type': 'custom',
            'start_date': self.day, 'end_date': self.day, 'employee_ids': [(6, 0, employee.ids)], 'payslip_status': 'draft'})
        report = self.env['report.hr_payslip_excel_report.payroll_review']
        data = report._data(wizard)
        row = data['register'][0]
        self.assertEqual((row['payable_days'], row['present'], row['absent'], row['worked_hours']), (1, 1, 0, 2.25))
        self.assertEqual((row['basic'], row['fine'], row['net']), (885, 643.64, 241.36))
        self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))
        wizard.report_type = 'review'
        self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))
        self.assertEqual(self.net(slip), 241.36)

    def test_five_attended_dates_include_short_day_and_preserve_existing_fine_snapshots(self):
        employee, contract, line = self.person()
        self.wizard(line).action_save()
        for day_text, fine_hours, amount in [('2026-10-21', 0, 0), ('2026-10-23', 5 / 60, 9.52),
                                             ('2026-10-24', 10 / 60, 17.88), ('2026-10-25', 0, 0)]:
            for start, end in [('09:45', '14:00'), ('14:45', '18:45')]:
                self.env['hr.attendance'].create({'employee_id': employee.id,
                    'check_in': day_text + ' ' + start + ':00', 'check_out': day_text + ' ' + end + ':00'})
            saved = self.env['bambus.attendance.day.review'].create({'date': day_text,
                'employee_id': employee.id, 'contract_id': contract.id})
            if amount:
                saved.write({'fine_state': 'approved', 'fine_hours': fine_hours, 'fine_amount': amount,
                             'fine_calculation_type': 'fixed', 'fine_rate': amount})
        slip = self.slip(employee, contract, '2026-10-21', '2026-10-25')
        self.assertEqual((slip.total_working_days, slip.total_regular_pay_amount), (5, 4425))
        self.assertEqual((slip.total_fine_amount, self.net(slip)), (671.04, 3753.96))
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 5)

    def test_explicit_paid_and_unpaid_half_leave_remain_separate(self):
        for paid in (False, True):
            employee, contract, line = self.person(spans=[('09:45', '14:00')])
            leave_type = self.env['hr.leave.type'].create({'name': 'Optional Paid Half' if paid else 'Optional Unpaid Half',
                'request_unit': 'half_day', 'requires_allocation': 'no', 'unpaid': not paid,
                'leave_validation_type': 'no_validation'})
            leave = self.env['hr.leave'].create({'employee_id': employee.id, 'holiday_status_id': leave_type.id,
                'request_date_from': self.day, 'request_date_to': self.day,
                'request_unit_half': True, 'request_date_from_period': 'pm'})
            self.assertEqual(leave.state, 'validate')
            slip = self.slip(employee, contract)
            self.assertEqual(slip.total_working_days, .5)
            self.assertEqual(slip.total_regular_pay_amount, 885 if paid else 442.5)
            self.assertFalse(self.wizard(line).fine_line_ids)

    def test_special_day_paid_credits_remain_template_controlled(self):
        self.template.weekly_off_thursday = True
        employee, contract, line = self.person('monthly', spans=[])
        slip = self.slip(employee, contract)
        self.assertEqual(slip.paid_weekly_off_days, 1)
        self.assertAlmostEqual(slip.total_regular_pay_amount, 8000 / 31)
        self.template.monthly_paid_weekly_off = False
        slip.action_compute_sheet()
        self.assertEqual(slip.total_regular_pay_amount, 0)
        self.template.weekly_off_thursday = False
        self.env['resource.calendar.leaves'].create({'name': 'Fine-only Holiday', 'calendar_id': self.calendar.id,
            'date_from': '2026-10-22 00:00:00', 'date_to': '2026-10-22 23:59:59'})
        self.template.monthly_paid_public_holiday = True
        slip.action_compute_sheet()
        self.assertEqual(slip.paid_public_holiday_days, 1)
        self.assertAlmostEqual(slip.total_regular_pay_amount, 8000 / 31)
        self.assertEqual(slip.total_fine_amount, 0)

    def test_old_session_approval_is_not_duplicated_when_switching_mode(self):
        employee, contract, line = self.person()
        line.write({'fine_state': 'approved', 'fine_hours': 2, 'fine_amount': 100,
                    'fine_review_data': {'early_am': {'state': 'approved', 'hours': 2,
                        'amount': 100, 'calculation_type': 'fixed', 'rate': 100, 'coverage': []}}})
        review = self.wizard(line)
        self.assertEqual(review.fine_line_ids.mapped('kind'), ['early_am'])
        self.assertFalse(review.can_review_sessions)
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_regular_pay_amount, slip.total_fine_amount, self.net(slip)), (885, 100, 785))

    def test_multiple_fine_components_reconcile_with_payslip_details(self):
        employee, contract, line = self.person(spans=[('09:45', '12:00'), ('15:00', '18:45')])
        review = self.wizard(line)
        self.assertEqual(set(review.fine_line_ids.mapped('kind')), {'early', 'late'})
        review.action_save()
        slip = self.slip(employee, contract)
        self.assertEqual(slip.total_regular_pay_amount, 885)
        self.assertAlmostEqual(sum(slip.attendance_deduction_detail_ids.mapped('amount')), slip.total_fine_amount, places=2)
        self.assertAlmostEqual(self.net(slip), 885 - slip.total_fine_amount, places=2)

    def test_wage_specific_basic_rule_and_header_use_new_regular_pay(self):
        basic = self.env.ref('hr_payroll_community.hr_rule_basic')
        specific = basic.copy({'name': 'Daily wage-specific test', 'code': 'BASIC_DAILY',
            'amount_select': 'code', 'amount_python_compute': 'result = contract.daily_wage * worked_days.DAYSWORKED.number_of_days'})
        self.structure.rule_ids = [(3, basic.id), (4, specific.id)]
        self.env['hr.salary.rule']._bambus_use_automation_amounts()
        employee, contract, line = self.person()
        self.wizard(line).action_save()
        slip = self.slip(employee, contract)
        self.assertEqual(slip.line_ids.filtered(lambda row: row.code == 'BASIC_DAILY').total, 885)
        self.assertEqual((slip.basic_pay, slip.gross_pay, slip.net_pay), (885, 885, 241.36))

    def test_outside_schedule_punch_does_not_hide_missing_morning(self):
        self.template.break_enabled = False
        employee, contract, line = self.person(spans=[('08:00', '08:30'), ('14:45', '18:45')])
        review = self.wizard(line)
        self.assertEqual(review.fine_line_ids.mapped('kind'), ['late'])
        self.assertAlmostEqual(review.fine_line_ids.hours, 250 / 60, places=6)

    def test_withheld_sunday_reconciles_eleven_paid_days_and_saved_money(self):
        # Isolate the two holidays in this reproduction from installed demo
        # global holidays; TransactionCase rolls this fixture change back.
        self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False), ('calendar_id', '=', False),
            ('date_from', '<=', '2026-10-31 23:59:59'),
            ('date_to', '>=', '2026-10-01 00:00:00')]).unlink()
        self.template.write({'weekly_off_sunday': True, 'monthly_paid_weekly_off': True,
            'monthly_paid_public_holiday': True, 'weekly_off_overtime_policy': 'all'})
        employee, contract, first_line = self.person('monthly')
        self.wizard(first_line).action_save()
        ot_rule = self.env['hr.salary.rule'].create({'name': 'Saved OT', 'code': 'OT', 'sequence': 20,
            'category_id': self.env.ref('hr_payroll_community.ALW').id,
            'condition_select': 'none', 'amount_select': 'code',
            'amount_python_compute': 'result = payslip.total_overtime_amount'})
        self.structure.rule_ids |= ot_rule
        for day in ('2026-10-02', '2026-10-20'):
            self.env['resource.calendar.leaves'].create({'name': 'Paid test holiday',
                'calendar_id': self.calendar.id, 'date_from': day + ' 09:00:00',
                'date_to': day + ' 17:00:00'})
        examples = [
            ('2026-10-18', [('09:45:00', '14:00:00'), ('14:45:00', '18:45:00')], 0, 0, 8.25, 387.10),
            ('2026-10-23', [('09:45:00', '12:00:00')], 3, 93.84, 0, 0),
            ('2026-10-24', [('09:45:00', '12:00:00')], 0, 0, 0, 0),
            ('2026-10-25', [('09:45:34', '14:00:00'), ('14:45:00', '18:45:00')], 0, 0, 8.25 - 34 / 3600, 386.65),
            ('2026-10-26', [('10:05:00', '14:00:00'), ('14:45:00', '18:45:00')], .25, 7.82, 0, 0),
            ('2026-10-27', [('09:45:00', '14:00:00'), ('14:55:00', '18:45:00')], 1 / 6, 5.21, 0, 0),
            ('2026-10-29', [('09:45:00', '12:00:00')], 0, 0, 0, 0),
        ]
        reviews = self.env['bambus.attendance.day.review']
        for day, spans, fine_hours, fine_amount, ot_hours, ot_amount in examples:
            for start, end in spans:
                self.env['hr.attendance'].create({'employee_id': employee.id,
                    'check_in': day + ' ' + start, 'check_out': day + ' ' + end})
            reviews |= self.env['bambus.attendance.day.review'].create({'date': day,
                'employee_id': employee.id, 'contract_id': contract.id,
                'fine_state': 'approved' if fine_amount else 'rejected',
                'fine_hours': fine_hours, 'fine_amount': fine_amount,
                'overtime_state': 'approved' if ot_amount else 'rejected',
                'overtime_hours': ot_hours, 'overtime_amount': ot_amount})
        self.env['bambus.attendance.dashboard'].set_dashboard_paid_day(
            employee.id, '2026-10-18', 'weekly_off', 'withhold', 'Sunday work earning only')
        slip = self.slip(employee, contract, '2026-10-01', '2026-10-31')
        self.assertEqual((slip.total_working_days, slip.paid_weekly_off_days, slip.paid_public_holiday_days), (6, 3, 2),
            str(slip._get_public_holiday_dates(contract, slip.date_from, slip.date_to, self.calendar.tz)))
        self.assertAlmostEqual(slip.total_regular_pay_amount, 8000 / 31 * 11)
        self.assertEqual((slip.weekend_worked, slip.withheld_weekly_off_worked_days), (1.5, 1))
        self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 11)
        self.assertEqual(slip.total_overtime_amount, 773.75)
        self.assertAlmostEqual(slip.total_fine_amount, 294.55, places=2)
        self.assertEqual(self.net(slip), 3317.91)
        self.assertEqual(sum(reviews.mapped('overtime_amount')), 773.75)
        if 'report.hr_payslip_excel_report.payroll_review' in self.env:
            wizard = self.env['payslip.excel.wizard'].create({'report_type': 'summary',
                'duration_type': 'custom', 'start_date': '2026-10-01', 'end_date': '2026-10-31',
                'employee_ids': [(6, 0, employee.ids)], 'payslip_status': 'draft'})
            report = self.env['report.hr_payslip_excel_report.payroll_review']
            for report_type in ('summary', 'review'):
                wizard.report_type = report_type
                row = report._data(wizard)['register'][0]
                self.assertEqual((row['payable_days'], row['basic'], row['overtime'], row['fine'], row['net']),
                                 (11, 2838.71, 773.75, 294.55, 3317.91))
                self.assertAlmostEqual(row['worked_hours'], 41.5 - 34 / 3600)
                self.assertEqual(row['weekly_off_worked'], 1.5)
                self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))
        saved_days = [(row.id, row.number_of_days, row.number_of_hours) for row in slip.worked_days_line_ids]
        saved_salary = [(row.id, row.total) for row in slip.line_ids]
        slip.state = 'done'
        self.env['bambus.attendance.dashboard'].set_dashboard_paid_day(
            employee.id, '2026-10-18', 'weekly_off', 'restore', 'Restore after snapshot')
        slip.action_compute_sheet()
        self.assertEqual([(row.id, row.number_of_days, row.number_of_hours) for row in slip.worked_days_line_ids], saved_days)
        self.assertEqual([(row.id, row.total) for row in slip.line_ids], saved_salary)
