from datetime import date, datetime, time, timedelta
from io import BytesIO
import zipfile

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestHourlyPayrollRefresh(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Hourly refresh calendar', 'tz': 'Asia/Kolkata',
            'attendance_ids': [(5, 0, 0)] + [(0, 0, {
                'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                'hour_from': 9, 'hour_to': 17}) for day in range(6)]})
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Hourly refresh policy', 'weekly_off_source': 'weekdays',
            'weekly_off_sunday': True, 'monthly_paid_weekly_off': True,
            'monthly_paid_public_holiday': False, 'overtime_enabled': False,
            'late_enabled': False, 'early_exit_enabled': False,
            'full_day_basis': 'fixed', 'full_day_hours': 8, 'half_day_hours': 4,
            'hourly_pay_use_template_limit': True, 'hourly_wage_hour_limit': 0})
        cls.env['hr.salary.rule']._bambus_use_automation_amounts()
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Hourly refresh salary', 'code': 'HOUR_REFRESH_TEST', 'parent_id': False,
            'rule_ids': [(6, 0, [cls.env.ref('hr_payroll_community.' + ref).id for ref in
                                ('hr_rule_basic', 'hr_rule_taxable', 'hr_rule_net')])]})

    def employee(self, basis='hourly', employee_type='employee'):
        employee = self.env['hr.employee'].create({
            'name': 'Hourly refresh ' + basis, 'resource_calendar_id': self.calendar.id,
            'employee_type': employee_type, 'attendance_automation_template_id': self.template.id})
        contract = self.env['hr.contract'].create({
            'name': 'Hourly refresh contract', 'employee_id': employee.id, 'state': 'open',
            'date_start': '2026-09-01', 'wage_type': basis, 'wage': 12000,
            'daily_wage': 885, 'hourly_rate': 53, 'hourly_wage_hour_limit': 0,
            'resource_calendar_id': self.calendar.id, 'struct_id': self.structure.id})
        return employee, contract

    def punch(self, employee, day, hours=1, start_hour=3.5):
        check_in = datetime.combine(fields.Date.to_date(day), time.min) + timedelta(hours=start_hour)
        return self.env['hr.attendance'].create({'employee_id': employee.id,
            'check_in': check_in, 'check_out': check_in + timedelta(hours=hours)})

    def slip(self, employee, contract):
        slip = self.env['hr.payslip'].create({'employee_id': employee.id, 'contract_id': contract.id,
            'struct_id': self.structure.id, 'date_from': '2026-09-01', 'date_to': '2026-09-30'})
        slip.action_compute_sheet()
        return slip

    def report(self, employee, report_type='summary'):
        wizard = self.env['payslip.excel.wizard'].create({
            'report_type': report_type, 'duration_type': 'custom',
            'start_date': '2026-09-01', 'end_date': '2026-09-30',
            'employee_ids': [(6, 0, employee.ids)], 'payslip_status': 'all'})
        data = self.env['report.hr_payslip_excel_report.payroll_review']._data(wizard)
        return wizard, data['register'][0]

    def net(self, slip):
        return slip.line_ids.filtered(lambda line: line.code == 'NET').total

    def test_existing_draft_refreshes_seconds_and_matches_fresh_computation(self):
        employee, contract = self.employee()
        punch = self.punch(employee, '2026-09-01', hours=4)
        slip = self.slip(employee, contract)
        self.assertEqual(self.net(slip), 212)
        old_id = slip.id
        punch.check_out += timedelta(seconds=12)
        slip.action_compute_sheet()
        self.assertEqual(slip.id, old_id)
        self.assertAlmostEqual(slip.total_worker_hours, 4 + 12 / 3600)
        self.assertAlmostEqual(self.net(slip), 212.18, places=2)
        fresh = self.slip(employee, contract)
        self.assertEqual(self.net(slip), self.net(fresh))
        self.assertEqual(slip.state, 'draft')

    def test_reference_hourly_totals_and_day_columns_for_employee_and_worker(self):
        regular = [date(2026, 9, day) for day in range(1, 31) if date(2026, 9, day).weekday() != 6]
        for i, (hours, count, expected) in enumerate([
            (94.38, 23, 5002.32), (105.98, 24, 5617.12),
            (73.5, 18, 3895.50), (103.68, 23, 5495.22)]):
            with self.subTest(hours=hours):
                employee, contract = self.employee(employee_type='employee' if i % 2 == 0 else 'worker')
                seconds = round(hours * 3600)
                base, extra = divmod(seconds, count)
                punches = self.env['hr.attendance']
                for j, day in enumerate(regular[:count]):
                    punches |= self.punch(employee, day, (base + (j < extra)) / 3600)
                slip = self.slip(employee, contract)
                work = slip.worked_days_line_ids.filtered(lambda line: line.code == 'WORK100')
                self.assertEqual(work.number_of_days, count)
                self.assertAlmostEqual(work.number_of_hours, hours)
                adjustment = round(hours * 60) * 60 - seconds
                punches[0].check_out += timedelta(seconds=adjustment)
                slip.action_compute_sheet()
                self.assertAlmostEqual(self.net(slip), expected, places=2)
                for report_type in ['summary', 'review']:
                    wizard, row = self.report(employee, report_type)
                    self.assertEqual((row['present'], row['payable_days']), (count, count))
                    self.assertAlmostEqual(row['net'], expected, places=2)
                    self.assertAlmostEqual(row['payable_hours'], round(hours * 60) / 60)
                    with zipfile.ZipFile(BytesIO(wizard._generate_xlsx())) as workbook:
                        self.assertIn('xl/workbook.xml', workbook.namelist())

    def test_add_delete_move_and_close_punches_refresh_days_without_duplicates(self):
        employee, contract = self.employee()
        first = self.punch(employee, '2026-09-01', .5)
        second = self.punch(employee, '2026-09-01', .5, start_hour=5)
        zero = self.punch(employee, '2026-09-03', 0)
        opened = self.env['hr.attendance'].create({'employee_id': employee.id, 'check_in': '2026-09-02 03:30:00'})
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_worker_hours, slip.total_worker_days), (1, 1))
        self.assertEqual(self.report(employee)[1]['present'], 1)
        opened.check_out = opened.check_in + timedelta(minutes=15)
        slip.action_compute_sheet()
        self.assertEqual((slip.total_worker_hours, slip.total_worker_days), (1.25, 2))
        second.unlink()
        first.unlink()
        slip.action_compute_sheet()
        self.assertEqual((slip.total_worker_hours, slip.total_worker_days), (.25, 1))
        opened.write({'check_in': '2026-10-01 03:30:00', 'check_out': '2026-10-01 03:45:00'})
        slip.action_compute_sheet()
        self.assertEqual((slip.total_worker_hours, slip.total_worker_days), (0, 0))
        self.assertEqual(self.report(employee)[1]['payable_days'], 0)
        self.assertTrue(zero.exists())

    def test_per_local_day_cap_and_raw_hours_are_preserved(self):
        employee, contract = self.employee()
        first = self.punch(employee, '2026-09-01', 1.5)
        second = self.punch(employee, '2026-09-01', 1.5, start_hour=6)
        self.template.hourly_wage_hour_limit = 2
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_worker_hours, slip.total_worker_days), (2, 1))
        self.assertEqual(self.net(slip), 106)
        contract.hourly_wage_hour_limit = 1
        self.template.hourly_pay_use_template_limit = False
        slip.action_compute_sheet()
        self.assertEqual(slip.total_worker_hours, 1)
        self.assertEqual(self.net(slip), 53)
        self.assertEqual(sum((first | second).mapped('worked_hours')), 3)

    def test_local_month_boundary_and_multiple_utc_dates_count_once(self):
        employee, contract = self.employee()
        self.env['hr.attendance'].create([
            {'employee_id': employee.id, 'check_in': '2026-08-31 19:00:00', 'check_out': '2026-08-31 20:00:00'},
            {'employee_id': employee.id, 'check_in': '2026-09-01 01:00:00', 'check_out': '2026-09-01 02:00:00'},
            {'employee_id': employee.id, 'check_in': '2026-09-30 19:00:00', 'check_out': '2026-09-30 20:00:00'},
        ])
        slip = self.slip(employee, contract)
        self.assertEqual((slip.total_worker_hours, slip.total_worker_days), (2, 1))
        self.assertEqual(self.report(employee)[1]['present'], 1)

    def test_finalized_or_cancelled_slips_are_not_recomputed(self):
        employee, contract = self.employee()
        punch = self.punch(employee, '2026-09-01', 1)
        for state in ['done', 'cancel']:
            with self.subTest(state=state):
                slip = self.slip(employee, contract)
                saved = [(line.id, line.total) for line in slip.line_ids]
                saved_hours = slip.total_worker_hours
                slip.state = state
                punch.check_out += timedelta(minutes=15)
                slip.action_compute_sheet()
                self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
                self.assertEqual(slip.total_worker_hours, saved_hours)
        editable = self.slip(employee, contract)
        editable.state = 'verify'
        punch.check_out += timedelta(minutes=15)
        editable.action_compute_sheet()
        self.assertEqual(editable.state, 'verify')
        self.assertAlmostEqual(editable.total_worker_hours, 1.75)

    def test_export_does_not_recompute_saved_salary_and_custom_rows_survive(self):
        employee, contract = self.employee()
        self.punch(employee, '2026-09-01', 1)
        slip = self.slip(employee, contract)
        custom = self.env['hr.payslip.worked.days'].create({'name': 'Custom input days', 'code': 'CUSTOM_HOURLY',
            'payslip_id': slip.id, 'contract_id': contract.id, 'number_of_days': .25, 'number_of_hours': .25})
        saved = [(line.id, line.total) for line in slip.line_ids]
        self.punch(employee, '2026-09-02', 1)
        wizard, row = self.report(employee)
        wizard._generate_xlsx()
        self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
        self.assertEqual(row['net'], 53)
        slip.action_compute_sheet()
        self.assertEqual(self.net(slip), 106)
        self.assertTrue(custom.exists())
        self.assertEqual(self.report(employee)[1]['payable_days'], 2)

    def test_monthly_and_daily_normal_pay_remain_unchanged(self):
        for basis, expected in [('monthly', 2000), ('daily', 1770)]:
            with self.subTest(basis=basis):
                employee, contract = self.employee(basis)
                self.punch(employee, '2026-09-01', 8)
                self.punch(employee, '2026-09-06', 8)
                slip = self.slip(employee, contract)
                self.assertEqual(slip.total_regular_pay_amount, expected)
                original = self.net(slip)
                slip.action_compute_sheet()
                self.assertEqual(self.net(slip), original)
