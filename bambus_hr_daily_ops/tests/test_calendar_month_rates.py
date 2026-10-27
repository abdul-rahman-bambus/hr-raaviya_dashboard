"""Calendar-month salary basis across payroll, detection and HR reviews."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestCalendarMonthRates(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Calendar-month 8h schedule', 'tz': 'UTC',
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                'hour_from': 9, 'hour_to': 17,
            }) for day in range(6)],
        })
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Calendar-month rules', 'weekly_off_source': 'weekdays',
            'weekly_off_sunday': True, 'monthly_paid_weekly_off': True,
            'monthly_paid_public_holiday': True, 'full_day_basis': 'fixed',
            'full_day_hours': 8, 'half_day_hours': 4, 'late_grace_minutes': 5,
            'early_exit_enabled': False, 'break_enabled': False,
            'weekly_off_overtime_policy': 'all', 'overtime_rate_policy': 'salary_multiplier',
            'overtime_calculation_type': 'salary_1_5', 'fine_calculation_type': 'salary_minute',
        })
        cls.env['hr.salary.rule']._bambus_use_automation_amounts()
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Calendar-month payroll', 'code': 'CAL_MONTH_TEST', 'parent_id': False,
            'rule_ids': [(6, 0, [cls.env.ref(ref).id for ref in (
                'hr_payroll_community.hr_rule_basic', 'hr_payroll_community.hr_rule_taxable',
                'hr_payroll_community.hr_rule_net')])],
        })

        for code, category, expression in (
            ('OT', 'ALW', 'payslip.total_overtime_amount'),
            ('PH', 'ALW', 'payslip.total_public_holiday_amount'),
            ('LF', 'DED', '-payslip.total_fine_amount'),
        ):
            cls.structure.rule_ids |= cls.env['hr.salary.rule'].create({
                'name': 'Calendar-month ' + code, 'code': code, 'sequence': 35,
                'category_id': cls.env.ref('hr_payroll_community.' + category).id,
                'condition_select': 'none', 'amount_select': 'code',
                'amount_python_compute': 'result = ' + expression,
            })

    def worker(self, basis='monthly', start='2023-01-01', end=False, calendar=None):
        calendar = calendar if calendar is not None else self.calendar
        employee = self.env['hr.employee'].create({
            'name': 'Calendar-month ' + basis, 'resource_calendar_id': calendar.id,
            'attendance_automation_template_id': self.template.id,
        })
        contract = self.env['hr.contract'].create({
            'name': 'Calendar-month contract', 'employee_id': employee.id,
            'resource_calendar_id': calendar.id, 'date_start': start, 'date_end': end,
            'wage_type': basis, 'wage': 12000, 'daily_wage': 100, 'hourly_rate': 50,
            'hourly_wage_hour_limit': 0, 'struct_id': self.structure.id,
        })
        return employee, contract

    def punches(self, employee, start, end, excluded=()):
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        dates = (start + timedelta(days=i) for i in range((end - start).days + 1))
        return self.env['hr.attendance'].create([{
            'employee_id': employee.id, 'check_in': datetime.combine(day, time(9)),
            'check_out': datetime.combine(day, time(17)),
        } for day in dates if day.weekday() != 6 and day not in excluded])

    def slip(self, employee, contract, start, end):
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id, 'date_from': start, 'date_to': end,
        })
        slip.action_compute_sheet()
        return slip

    def line(self, employee, contract, day):
        line = self.env['bambus.attendance.day.review'].create({
            'date': day, 'employee_id': employee.id, 'contract_id': contract.id})
        line._compute_day_data()
        return line

    def test_full_28_29_30_31_day_months_pay_exact_monthly_wage(self):
        for year, month in ((2023, 2), (2024, 2), (2026, 4), (2026, 7)):
            with self.subTest(year=year, month=month):
                start = date(year, month, 1)
                end = date(year, month, monthrange(year, month)[1])
                employee, contract = self.worker()
                self.punches(employee, start, end)
                slip = self.slip(employee, contract, start, end)
                self.assertAlmostEqual(slip.total_regular_pay_amount, 12000, places=2)
                self.assertAlmostEqual(slip.basic_pay, 12000, places=2)
                self.assertAlmostEqual(slip.net_pay, 12000, places=2)
                self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), end.day)

    def test_partial_february_uses_full_calendar_month_not_employment_days(self):
        employee, contract = self.worker(start='2024-02-15', end='2024-02-29')
        self.punches(employee, '2024-02-15', '2024-02-29')
        slip = self.slip(employee, contract, '2024-02-01', '2024-02-29')
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000 * 15 / 29)
        self.assertAlmostEqual(slip.basic_pay, 12000 * 15 / 29, places=2)

    def test_cross_month_period_prices_each_work_date_in_its_own_month(self):
        employee, contract = self.worker()
        self.punches(employee, '2024-01-30', '2024-02-02')
        slip = self.slip(employee, contract, '2024-01-30', '2024-02-02')
        self.assertAlmostEqual(slip.total_regular_pay_amount, 2 * 12000 / 31 + 2 * 12000 / 29)

    def test_absence_paid_leave_and_unpaid_leave_use_calendar_day_rate(self):
        employee, contract = self.worker()
        excluded = date(2024, 2, 7)
        self.punches(employee, '2024-02-01', '2024-02-29', excluded={excluded})
        slip = self.slip(employee, contract, '2024-02-01', '2024-02-29')
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000 * 28 / 29)
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Calendar-month paid leave', 'requires_allocation': 'no',
            'code': 'CAL_PAID_TEST'})
        leave = self.env['hr.leave'].create({
            'employee_id': employee.id, 'holiday_status_id': leave_type.id,
            'request_date_from': excluded, 'request_date_to': excluded})
        leave.action_approve()
        if leave.state != 'validate':
            leave.action_validate()
        slip.action_compute_sheet()
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000)
        leave_type.unpaid = True
        slip.action_compute_sheet()
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000 * 28 / 29)

    def test_special_day_credits_and_approval_rates_share_calendar_month_basis(self):
        # Use a Sunday in each target calendar month.
        for year, month, day in ((2023, 2, 5), (2024, 2, 4), (2026, 4, 5), (2026, 7, 5)):
            work_date = date(year, month, day)
            daily = 12000 / monthrange(year, month)[1]
            with self.subTest(date=work_date):
                employee, contract = self.worker()
                slip = self.slip(employee, contract, work_date, work_date)
                self.assertAlmostEqual(slip.paid_weekly_off_amount, daily)
                self.assertAlmostEqual(slip.total_regular_pay_amount, daily)
                self.env['resource.calendar.leaves'].create({
                    'name': 'Calendar-month holiday', 'calendar_id': self.calendar.id,
                    'date_from': datetime.combine(work_date, time.min),
                    'date_to': datetime.combine(work_date, time.max)})
                slip.action_compute_sheet()
                self.assertEqual(slip.paid_weekly_off_amount, 0)
                self.assertAlmostEqual(slip.paid_public_holiday_amount, daily)
                self.assertAlmostEqual(slip.total_regular_pay_amount, daily)
                line = self.line(employee, contract, work_date)
                wizard = self.env['bambus.hr.overtime.wizard'].new({
                    'line_id': line.id, 'overtime_hours': 8, 'calculation_type': 'salary_2'})
                self.assertAlmostEqual(wizard.overtime_amount, wizard.currency_id.round(2 * daily))

    def test_detected_fines_and_review_amounts_use_the_historical_month(self):
        for work_date in (date(2023, 2, 6), date(2024, 2, 5), date(2026, 4, 6), date(2026, 7, 6)):
            with self.subTest(date=work_date):
                employee, contract = self.worker()
                attendance = self.env['hr.attendance'].create({
                    'employee_id': employee.id, 'check_in': datetime.combine(work_date, time(9, 10)),
                    'check_out': datetime.combine(work_date, time(17))})
                self.env['hr.attendance.overtime'].bambus_recompute_range(employee.ids, work_date, work_date)
                daily = 12000 / monthrange(work_date.year, work_date.month)[1]
                expected_fine = daily * 5 / 480
                self.assertAlmostEqual(attendance.bambus_fine_hours, 5 / 60)
                self.assertAlmostEqual(attendance.bambus_fine_amount, contract.company_id.currency_id.round(expected_fine))
                line = self.line(employee, contract, work_date)
                fine = self.env['bambus.hr.fine.wizard'].new({
                    'line_id': line.id, 'fine_hours': 5 / 60, 'calculation_type': 'salary_minute'})
                self.assertAlmostEqual(fine.fine_amount, fine.currency_id.round(expected_fine))
                review = self.env['bambus.hr.attendance.review.wizard'].with_context(default_line_id=line.id).create({})
                self.assertAlmostEqual(sum(review.fine_line_ids.mapped('amount')), fine.currency_id.round(expected_fine))
                overtime = self.env['bambus.hr.overtime.wizard'].new({
                    'line_id': line.id, 'overtime_hours': 8, 'calculation_type': 'salary_1_5'})
                self.assertAlmostEqual(overtime.overtime_amount, overtime.currency_id.round(daily * 1.5))
                overtime.write({'calculation_type': 'fixed_hour', 'rate': 75})
                self.assertEqual(overtime.overtime_amount, 600)

    def test_review_switch_between_months_uses_each_lines_date(self):
        employee, contract = self.worker()
        january = self.line(employee, contract, date(2024, 1, 31))
        february = self.line(employee, contract, date(2024, 2, 1))
        wizard = self.env['bambus.hr.overtime.wizard'].with_context(default_line_id=january.id).create({
            'line_id': january.id, 'overtime_hours': 8, 'calculation_type': 'salary_1'})
        self.assertAlmostEqual(wizard.overtime_amount, wizard.currency_id.round(12000 / 31))
        # Attendance dates are read-only. Switching the review's source line
        # must use its month even when the employee and contract stay the same.
        wizard.line_id = february
        self.assertAlmostEqual(wizard.overtime_amount, wizard.currency_id.round(12000 / 29))

    def test_local_attendance_date_determines_month_at_utc_boundary(self):
        calendar = self.calendar.copy({'name': 'Calendar-month Kolkata', 'tz': 'Asia/Kolkata'})
        employee, contract = self.worker(calendar=calendar)
        self.env['hr.attendance'].create({
            'employee_id': employee.id, 'check_in': '2024-02-29 20:00:00',
            'check_out': '2024-03-01 04:00:00'})
        slip = self.slip(employee, contract, '2024-03-01', '2024-03-01')
        self.assertAlmostEqual(slip.total_regular_pay_amount, 12000 / 31)

    def test_daily_and_hourly_contracts_keep_explicit_rates(self):
        for basis, expected in (('daily', 100), ('hourly', 400)):
            with self.subTest(basis=basis):
                employee, contract = self.worker(basis=basis)
                self.punches(employee, '2024-02-01', '2024-02-01')
                slip = self.slip(employee, contract, '2024-02-01', '2024-02-01')
                self.assertAlmostEqual(slip.total_regular_pay_amount, expected)
                self.assertAlmostEqual(slip.basic_pay, expected)

    def test_approved_adjustments_and_final_salary_lines_are_not_repriced(self):
        employee, contract = self.worker()
        work_date = date(2026, 7, 6)
        self.env['hr.attendance'].create({
            'employee_id': employee.id, 'check_in': datetime.combine(work_date, time(9, 10)),
            'check_out': datetime.combine(work_date, time(17))})
        line = self.line(employee, contract, work_date)
        fine = self.env['bambus.hr.fine.wizard'].with_context(default_line_id=line.id).create({
            'fine_hours': 5 / 60, 'calculation_type': 'salary_minute'})
        fine.action_save()
        overtime = self.env['bambus.hr.overtime.wizard'].with_context(default_line_id=line.id).create({
            'overtime_hours': 8, 'calculation_type': 'salary_1_5'})
        overtime.action_save()
        expected_ot = line.currency_id.round(12000 / 31 * 1.5)
        expected_fine = line.currency_id.round(12000 / 31 * 5 / 480)
        self.assertEqual((line.overtime_amount, line.fine_amount), (expected_ot, expected_fine))
        slip = self.slip(employee, contract, work_date, work_date)
        self.assertEqual(slip.line_ids.filtered(lambda row: row.code == 'OT').total, expected_ot)
        self.assertEqual(slip.line_ids.filtered(lambda row: row.code == 'LF').total, -expected_fine)
        slip.state = 'done'
        salary_lines = [(row.id, row.total) for row in slip.line_ids]
        contract.wage = 24000
        self.env['hr.attendance.overtime'].bambus_recompute_range(employee.ids, work_date, work_date)
        line.action_refresh()
        self.assertEqual((line.overtime_amount, line.fine_amount), (expected_ot, expected_fine))
        self.assertEqual([(row.id, row.total) for row in slip.line_ids], salary_lines)
