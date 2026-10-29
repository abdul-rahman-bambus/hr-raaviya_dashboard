from datetime import datetime
import io
import zipfile

import xlsxwriter
from xml.etree import ElementTree as ET

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user


class TestPayrollReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Payroll Review Calendar', 'tz': 'Asia/Kolkata', 'company_id': cls.company.id,
            'attendance_ids': [Command.create({'name': 'Monday', 'dayofweek': '0', 'day_period': 'morning',
                                               'hour_from': 9., 'hour_to': 17.})],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': '=Review Employee', 'company_id': cls.company.id, 'resource_calendar_id': cls.calendar.id,
        })
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Review Contract', 'employee_id': cls.employee.id, 'company_id': cls.company.id,
            'resource_calendar_id': cls.calendar.id, 'date_start': '2026-09-01', 'wage': 9000., 'wage_type': 'monthly',
        })
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Review Sunday Template', 'company_id': cls.company.id,
            'weekly_off_source': 'weekdays', 'weekly_off_sunday': True,
            'weekly_off_overtime_policy': 'all',
        })
        cls.employee.attendance_automation_template_id = cls.template
        cls.report = cls.env['report.hr_payslip_excel_report.payroll_review']

    def wizard(self, **values):
        return self.env['payslip.excel.wizard'].create({
            'report_type': 'review', 'company_id': self.company.id, 'duration_type': 'custom',
            'start_date': '2026-09-01', 'end_date': '2026-09-30',
            'employee_ids': [Command.set(self.employee.ids)], **values,
        })

    def slip(self, **values):
        return self.env['hr.payslip'].create({
            'name': 'Review September', 'employee_id': self.employee.id,
            'contract_id': self.contract.id, 'company_id': self.company.id,
            'date_from': '2026-09-01', 'date_to': '2026-09-30', **values,
        })

    def salary(self, slip, code, total, category):
        rule = self.env['hr.salary.rule'].create({'name': code, 'code': code,
            'category_id': self.env.ref('hr_payroll_community.' + category).id})
        return self.env['hr.payslip.line'].create({'name': code, 'code': code, 'salary_rule_id': rule.id,
            'category_id': rule.category_id.id, 'slip_id': slip.id, 'employee_id': slip.employee_id.id,
            'contract_id': slip.contract_id.id, 'amount': total, 'quantity': 1., 'rate': 100.})

    def finance(self, slip):
        for code, amount, category in [('BASIC', 8000., 'BASIC'), ('OT', 300., 'ALW'),
                                      ('PH', 200., 'ALW'), ('HRA', 500., 'ALW'),
                                      ('LATE', -100., 'DED'), ('LO', -200., 'DED'),
                                      ('GROSS', 9000., 'GROSS'), ('NET', 8700., 'NET')]:
            self.salary(slip, code, amount, category)
        self.env['hr.payslip.worked.days'].create({'name': 'Paid days', 'code': 'WORK100',
            'payslip_id': slip.id, 'contract_id': slip.contract_id.id, 'number_of_days': 26., 'number_of_hours': 208.})

    def test_salary_without_attendance_is_not_skipped(self):
        slip = self.slip()
        self.finance(slip)
        data = self.report._data(self.wizard())
        self.assertEqual(len(data['register']), 1)
        row = data['register'][0]
        self.assertEqual((row['basic'], row['overtime'], row['holiday_pay'], row['allowances']), (8000, 300, 200, 500))
        self.assertEqual((row['fine'], row['advance'], row['deductions'], row['net']), (100, 200, 300, 8700))
        self.assertEqual(row['payable_days'], 26)
        self.assertEqual(row['worked_hours'], 0)
        self.assertEqual(data['summary'][0]['net'], 8700)

    def test_duplicate_period_uses_latest_computed_slip_once(self):
        old = self.slip()
        self.finance(old)
        latest = self.slip()
        self.finance(latest)
        data = self.report._data(self.wizard())
        self.assertEqual(len(data['register']), 1)
        self.assertEqual(data['summary'][0]['payslips'], 1)
        self.assertEqual(data['summary'][0]['net'], 8700)
        self.assertEqual(data['excluded_count'], 1)
        self.assertIn('Duplicate Payslip Excluded', {item['issue'] for item in data['exceptions']})
        self.assertTrue(old.exists() and latest.exists())

    def test_confirmed_slip_precedes_new_draft_and_computed_precedes_empty(self):
        done = self.slip(state='done')
        self.finance(done)
        self.finance(self.slip())
        selected, excluded = self.report._resolve_duplicate_periods(self.wizard(payslip_status='all')._selected_payslips())
        self.assertEqual(selected, done)
        done.state = 'draft'
        empty = self.slip()
        selected, excluded = self.report._resolve_duplicate_periods(self.wizard()._selected_payslips())
        self.assertNotIn(empty, selected)

    def test_summary_merges_split_periods_without_losing_salary(self):
        self.finance(self.slip(date_to='2026-09-15'))
        self.finance(self.slip(date_from='2026-09-16'))
        data = self.report._data(self.wizard(report_type='summary'))
        rows = self.report._employee_summary_rows(data['register'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['net'], 17400)
        self.assertEqual(data['excluded_count'], 0)

    def test_summary_credit_note_reverses_money_without_repeating_days(self):
        self.finance(self.slip())
        self.finance(self.slip(credit_note=True))
        data = self.report._data(self.wizard(report_type='summary'))
        rows = self.report._employee_summary_rows(data['register'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['net'], 0)
        self.assertEqual(rows[0]['payable_days'], 26)

    def test_different_contracts_are_preserved_and_partial_overlap_is_flagged(self):
        self.finance(self.slip())
        other_contract = self.contract.copy({'name': 'Second Contract'})
        self.finance(self.slip(contract_id=other_contract.id))
        data = self.report._data(self.wizard(report_type='summary'))
        self.assertEqual(data['excluded_count'], 0)
        rows = self.report._employee_summary_rows(data['register'])
        self.assertEqual(rows[0]['net'], 17400)
        self.assertEqual(rows[0]['payable_days'], 26)
        self.finance(self.slip(date_from='2026-09-15'))
        data = self.report._data(self.wizard(report_type='summary'))
        self.assertIsNone(self.report._employee_summary_rows(data['register'])[0]['payable_days'])

    def test_hrms_shortcut_opens_existing_report_action(self):
        menu = self.env.ref('hr_payslip_excel_report.menu_hrms_payroll_reports')
        self.assertEqual(menu.parent_id, self.env.ref('bambus_hr_daily_ops.menu_bambus_hrms_payroll'))
        self.assertEqual(menu.action, self.env.ref('hr_payslip_excel_report.hr_payslip_excel_report_action'))

    def test_credit_notes_reverse_salary_totals(self):
        self.finance(self.slip())
        self.finance(self.slip(credit_note=True))
        data = self.report._data(self.wizard())
        self.assertEqual(data['summary'][0]['net'], 0)
        self.assertFalse(any(item['issue'] == 'Overlapping Payslips' for item in data['exceptions']))

    def test_status_and_period_filters_keep_split_payslips(self):
        first = self.slip(date_to='2026-09-15', state='done')
        second = self.slip(date_from='2026-09-16', state='draft')
        self.slip(date_from='2026-08-01', date_to='2026-08-31')
        self.slip(state='cancel')
        wizard = self.wizard()
        self.assertEqual(wizard._selected_payslips(), second)
        wizard.payslip_status = 'all'
        self.assertEqual(set(wizard._selected_payslips().ids), {first.id, second.id})
        wizard.payslip_status = 'done'
        self.assertEqual(wizard._selected_payslips(), first)

    def test_missing_and_uncomputed_payslips_are_explicit(self):
        data = self.report._data(self.wizard())
        self.assertEqual(data['summary'][0]['missing'], 1)
        self.assertNotIn('net', data['register'][0])
        self.assertEqual(data['exceptions'][0]['issue'], 'No Matching Payslip')
        self.slip()
        data = self.report._data(self.wizard())
        self.assertIsNone(data['register'][0]['net'])
        self.assertIn('Uncomputed Payslip', {item['issue'] for item in data['exceptions']})

    def test_reconciliation_and_unmapped_days_flagged(self):
        slip = self.slip()
        self.finance(slip)
        slip.line_ids.filtered(lambda line: line.code == 'NET').amount = 8000
        slip.worked_days_line_ids.code = 'UNKNOWN'
        data = self.report._data(self.wizard())
        self.assertIsNone(data['register'][0]['payable_days'])
        self.assertIn('Salary Reconciliation', {item['issue'] for item in data['exceptions']})
        self.assertEqual(data['register'][0]['net'], 8000)

    def test_invalid_dates_and_company_rejected(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.wizard(start_date='2026-10-01')
        company = self.env['res.company'].create({'name': 'Other Payroll Company'})
        with self.assertRaises(ValidationError):
            self.wizard(company_id=company.id).with_context(allowed_company_ids=[self.company.id, company.id])._validate_scope()
        with self.assertRaises(AccessError):
            self.wizard(company_id=company.id).with_context(allowed_company_ids=[self.company.id])._generate_xlsx()

    def test_department_and_employee_scope(self):
        department = self.env['hr.department'].create({'name': 'Review Department', 'company_id': self.company.id})
        self.employee.department_id = department
        self.slip()
        other = self.env['hr.employee'].create({'name': 'Other Staff', 'company_id': self.company.id})
        self.env['hr.payslip'].create({'name': 'Other Slip', 'employee_id': other.id, 'company_id': self.company.id,
            'date_from': '2026-09-01', 'date_to': '2026-09-30'})
        wizard = self.wizard(employee_ids=[Command.clear()], department_id=department.id)
        self.assertEqual(wizard._selected_payslips().employee_id, self.employee)

    def test_local_midnight_and_weekly_off_classification(self):
        slip = self.slip(date_from='2026-09-06', date_to='2026-09-07')
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': datetime(2026, 9, 6, 18, 30), 'check_out': datetime(2026, 9, 6, 22, 30)})
        data = self.report._data(self.wizard())
        sunday, monday = data['daily']
        self.assertEqual(sunday['classification'], 'Weekly Off')
        self.assertEqual(monday['classification'], 'Working Day')
        self.assertEqual(monday['worked'], 4)
        self.assertEqual(monday['check_in'], '00:00')
        self.assertEqual(sunday['policy'], 'All Worked Hours')

    def test_pending_and_approved_reviews_do_not_recalculate_salary(self):
        slip = self.slip(date_from='2026-09-07', date_to='2026-09-07')
        self.finance(slip)
        review_values = {'date': '2026-09-07', 'company_id': self.company.id}
        line = self.env['bambus.attendance.day.review'].create({**review_values, 'employee_id': self.employee.id,
            'overtime_state': 'submitted', 'overtime_detected_hours': 2,
            'fine_state': 'approved', 'fine_hours': 1, 'fine_amount': 125})
        data = self.report._data(self.wizard())
        self.assertEqual(data['register'][0]['net'], 8700)
        self.assertEqual(data['register'][0]['pending'], 1)
        self.assertEqual(data['daily'][0]['fine_approved'], 1)
        self.assertEqual(data['daily'][0]['fine_amount'], 125)
        self.assertIn('Pending Overtime', {item['issue'] for item in data['exceptions']})
        self.assertEqual(line.overtime_state, 'submitted')

    def test_unpaid_leave_days_are_excluded_from_payable_days(self):
        slip = self.slip()
        self.finance(slip)
        self.env['hr.leave.type'].create({'name': 'Unpaid Review', 'code': 'REVIEW_UNPAID', 'unpaid': True})
        self.env['hr.payslip.worked.days'].create({'name': 'Unpaid', 'code': 'REVIEW_UNPAID',
            'payslip_id': slip.id, 'contract_id': self.contract.id, 'number_of_days': 2})
        self.assertEqual(self.report._payable_days(slip), 26)

    def test_hourly_report_preserves_payroll_cap_and_hr_hours(self):
        self.contract.write({'wage_type': 'hourly', 'hourly_rate': 100, 'hourly_wage_hour_limit': 5})
        self.template.hourly_pay_use_template_limit = False
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': datetime(2026, 9, 7, 3, 30), 'check_out': datetime(2026, 9, 7, 11, 30)})
        review_values = {'date': '2026-09-07', 'company_id': self.company.id}
        self.env['bambus.attendance.day.review'].create({**review_values, 'employee_id': self.employee.id,
            'hourly_pay_state': 'approved', 'hourly_pay_hours': 7, 'hourly_pay_amount': 700})
        self.finance(self.slip(date_from='2026-09-07', date_to='2026-09-07'))
        data = self.report._data(self.wizard())
        self.assertEqual(data['register'][0]['payable_hours'], 5)
        self.assertEqual(data['register'][0]['basis'], 'Hourly Wage')
        self.assertEqual(data['daily'][0]['hourly_approved'], 7)
        self.assertEqual(data['register'][0]['worked_hours'], 8)

    def test_paid_leave_is_not_counted_on_weekly_off(self):
        leave_type = self.env['hr.leave.type'].create({'name': 'Review Paid Leave',
            'requires_allocation': 'no', 'leave_validation_type': 'no_validation'})
        self.env['hr.leave'].create({'name': 'Review Paid Leave', 'employee_id': self.employee.id,
            'holiday_status_id': leave_type.id, 'request_date_from': '2026-09-06',
            'request_date_to': '2026-09-07'})
        self.slip(date_from='2026-09-06', date_to='2026-09-07')
        data = self.report._data(self.wizard())
        self.assertEqual(data['register'][0]['paid_leave'], 1)
        self.assertEqual(data['register'][0]['weekly_off'], 1)
        self.assertEqual(data['register'][0]['absent'], 0)

    def test_partial_paid_leave_keeps_work_and_leave_separate(self):
        self.calendar.attendance_ids.hour_to = 13
        self.calendar.attendance_ids = [Command.create({'name': 'Monday Afternoon', 'dayofweek': '0',
            'day_period': 'afternoon', 'hour_from': 13, 'hour_to': 17})]
        leave_type = self.env['hr.leave.type'].create({'name': 'Review Half Leave',
            'request_unit': 'half_day', 'requires_allocation': 'no', 'leave_validation_type': 'no_validation'})
        self.env['hr.leave'].create({'name': 'Review Half Leave', 'employee_id': self.employee.id,
            'holiday_status_id': leave_type.id, 'request_date_from': '2026-09-07', 'request_date_to': '2026-09-07',
            'request_unit_half': True, 'request_date_from_period': 'pm'})
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': datetime(2026, 9, 7, 3, 30), 'check_out': datetime(2026, 9, 7, 7, 30)})
        self.slip(date_from='2026-09-07', date_to='2026-09-07')
        data = self.report._data(self.wizard())
        row = data['register'][0]
        self.assertEqual((row['present'], row['paid_leave'], row['half_days'], row['absent']), (.5, .5, 1, 0))

    def test_payroll_officer_record_rules_are_preserved(self):
        department = self.env['hr.department'].create({'name': 'Restricted Payroll', 'company_id': self.company.id})
        self.employee.department_id = department
        slip = self.slip()
        officer = new_test_user(self.env, login='review_officer',
            groups='hr_payroll_community.group_hr_payroll_community_user')
        wizard = self.env['payslip.excel.wizard'].with_user(officer).create({
            'report_type': 'review', 'duration_type': 'custom', 'start_date': '2026-09-01', 'end_date': '2026-09-30',
            'employee_ids': [Command.set(self.employee.ids)]})
        self.assertNotIn(slip, wizard._selected_payslips())

    def test_regular_users_cannot_export_payroll(self):
        user = new_test_user(self.env, login='payroll_review_employee', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.wizard().with_user(user)._generate_xlsx()

    def test_workbook_tabs_numeric_totals_and_formula_like_names(self):
        slip = self.slip()
        self.finance(slip)
        content = self.wizard()._generate_xlsx()
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            workbook = ET.fromstring(archive.read('xl/workbook.xml'))
            self.assertEqual([s.attrib['name'] for s in workbook.findall('s:sheets/s:sheet', ns)],
                ['Payroll Summary', 'Employee Payroll Register', 'Attendance & Adjustments', 'Review Exceptions'])
            register = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
            self.assertIsNotNone(register.find('s:autoFilter', ns))
            self.assertIsNone(register.find('s:sheetViews/s:sheetView/s:pane', ns))
            view = workbook.find('s:bookViews/s:workbookView', ns)
            self.assertEqual(view.attrib['showHorizontalScroll'], '0')
            self.assertEqual(view.attrib['showVerticalScroll'], '0')
            name_cell = register.find("s:sheetData/s:row/s:c[@r='B7']", ns)
            self.assertEqual(name_cell.attrib['t'], 's')
            self.assertIsNone(name_cell.find('s:f', ns))
            net = register.find("s:sheetData/s:row/s:c[@r='AJ7']/s:v", ns)
            self.assertEqual(float(net.text), 8700)
        self.assertEqual(slip.line_ids.filtered(lambda line: line.code == 'NET').total, 8700)

    def test_detailed_summary_salary_components_and_contract_salary(self):
        self.finance(self.slip())
        data = self.report._data(self.wizard(report_type='summary'))
        row = self.report._employee_summary_rows(data['register'])[0]
        self.assertEqual(row['ctc'], 9000)
        self.assertEqual((row['basic'], row['overtime'], row['public_holiday_pay'], row['fine']),
                         (8000, 300, 200, 100))
        self.assertEqual((row['earnings'], row['deductions'], row['net']), (9000, 300, 8700))

    def test_summary_public_holiday_takes_precedence_over_weekly_off(self):
        self.env['resource.calendar.leaves'].create({'name': 'Sunday Public Holiday',
            'calendar_id': self.calendar.id, 'date_from': datetime(2026, 9, 5, 18, 30),
            'date_to': datetime(2026, 9, 6, 18, 29, 59)})
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': datetime(2026, 9, 6, 3, 30), 'check_out': datetime(2026, 9, 6, 11, 30)})
        self.finance(self.slip(date_from='2026-09-06', date_to='2026-09-06'))
        data = self.report._data(self.wizard(report_type='summary'))
        row = self.report._employee_summary_rows(data['register'])[0]
        self.assertEqual((row['holidays'], row['holiday_worked'], row['weekly_off_leave']), (1, 1, 0))
        self.assertEqual(row['worked_hours'], 8)
        self.assertEqual(row['public_holiday_pay'], 200)
        self.assertEqual(row['net'], 8700)

    def test_paid_holiday_policy_reconciles_register_daily_and_summary(self):
        self.env['resource.calendar.leaves'].create({'name': 'Paid Sunday Holiday',
            'calendar_id': self.calendar.id, 'date_from': datetime(2026, 9, 5, 18, 30),
            'date_to': datetime(2026, 9, 6, 18, 29, 59)})
        slip = self.slip(date_from='2026-09-06', date_to='2026-09-06')
        for enabled in (True, False):
            self.template.monthly_paid_public_holiday = enabled
            slip.action_compute_sheet()
            data = self.report._data(self.wizard(report_type='review'))
            row = data['register'][0]
            self.assertEqual(row['paid_holiday_days'], int(enabled))
            self.assertEqual(row['weekly_off_leave'], 0)
            self.assertEqual(slip.paid_public_holiday_days, int(enabled))
            self.assertEqual(slip.total_regular_pay_amount, 300 * int(enabled))
            self.assertEqual(data['daily'][0]['status'], 'Paid Public Holiday' if enabled else 'No Attendance')
            self.assertEqual(data['daily'][0]['paid_public_holiday'], int(enabled))
            self.assertEqual(self.report._employee_summary_rows(data['register'])[0]['paid_holiday_days'], int(enabled))

    def test_worked_paid_weekly_off_report_keeps_credit_distinct_from_work(self):
        slip = self.slip(date_from='2026-09-06', date_to='2026-09-06')
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': datetime(2026, 9, 6, 3, 30), 'check_out': datetime(2026, 9, 6, 7, 30)})
        slip.action_compute_sheet()
        data = self.report._data(self.wizard(report_type='review'))
        row = data['register'][0]
        self.assertEqual((row['weekly_off_leave'], row['weekly_off_worked'], row['payable_days']), (1, .5, 1))
        self.assertEqual(data['daily'][0]['status'], 'Worked Paid Weekly Off')

    def test_withheld_worked_special_dates_excluded_from_saved_payable_days_and_exports(self):
        self.env.user.tz = 'Asia/Kolkata'
        self.env['resource.calendar.leaves'].create({'name': 'Withheld Monday holiday',
            'calendar_id': self.calendar.id, 'date_from': '2026-09-06 18:30:00',
            'date_to': '2026-09-07 18:29:59'})
        self.template.monthly_paid_public_holiday = True
        for day, kind in [('2026-09-06', 'weekly_off'), ('2026-09-07', 'public_holiday')]:
            self.env['hr.attendance'].create({'employee_id': self.employee.id,
                'check_in': day + ' 03:30:00', 'check_out': day + ' 11:30:00'})
            slip = self.slip(date_from=day, date_to=day)
            info = self.env['bambus.attendance.dashboard']._paid_day_info(
                self.employee, slip.date_from, self.contract)
            self.assertEqual((info['kind'], info['eligible']), (kind, True), (day, info))
            self.env['bambus.attendance.dashboard'].set_dashboard_paid_day(
                self.employee.id, day, kind, 'withhold', 'Pay only separately approved earnings')
            slip.action_compute_sheet()
            self.assertEqual(self.report._payable_days(slip), 0)
            self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_hours')), 8)
        for report_type in ('review', 'summary'):
            wizard = self.wizard(report_type=report_type, payslip_status='draft')
            data = self.report._data(wizard)
            self.assertEqual(len(data['register']), 2)
            self.assertTrue(all(row['payable_days'] == 0 for row in data['register']))
            self.assertEqual(sum(row['worked_hours'] for row in data['register']), 16)
            self.assertEqual(sum(row['present'] for row in data['register']), 2)
            self.assertEqual(self.report._employee_summary_rows(data['register'])[0]['payable_days'], 0)
            self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))

    def test_weekly_off_switch_matches_payroll_attendance_and_summary(self):
        slip = self.slip(date_from='2026-09-06', date_to='2026-09-06')
        report = self.env['report.attendance_custom_report.attendance_xlsx']
        from types import SimpleNamespace
        period = SimpleNamespace(date_start=slip.date_from, date_end=slip.date_to)
        for enabled in (True, False, True):
            self.template.monthly_paid_weekly_off = enabled
            daily = report._compute_employee_daily(self.employee, period, contract=self.contract)
            self.assertEqual(daily[slip.date_from]['paid_weekly_off'], enabled)
            data = self.report._data(self.wizard(report_type='review'))
            row = data['register'][0]
            self.assertEqual(row['weekly_off_leave'], int(enabled))
            self.assertEqual(row['weekly_off'], 1)
            self.assertEqual(slip.paid_weekly_off_days, int(enabled))
            self.assertEqual(slip.total_regular_pay_amount, 300 * int(enabled))
            self.assertEqual(data['daily'][0]['status'], 'Paid Weekly Off' if enabled else 'No Attendance')
            summary = self.report._employee_summary_rows(data['register'])[0]
            self.assertEqual(summary['weekly_off_leave'], int(enabled))

    def test_summary_unused_weekly_off_and_absence_are_separate(self):
        self.finance(self.slip(date_from='2026-09-06', date_to='2026-09-07'))
        data = self.report._data(self.wizard(report_type='summary'))
        row = self.report._employee_summary_rows(data['register'])[0]
        self.assertEqual((row['weekly_off_leave'], row['weekly_off_worked'], row['absent'], row['holidays']),
                         (1, 0, 1, 0))

    def test_detailed_summary_headers_and_decimal_hours(self):
        self.env['hr.attendance'].create({'employee_id': self.employee.id,
            'check_in': datetime(2026, 9, 7, 3, 45), 'check_out': datetime(2026, 9, 7, 13, 15)})
        review_values = {'date': '2026-09-07', 'company_id': self.company.id}
        self.env['bambus.attendance.day.review'].create({**review_values, 'employee_id': self.employee.id,
            'overtime_state': 'approved', 'overtime_hours': 1.75, 'overtime_amount': 300,
            'fine_state': 'approved', 'fine_hours': .25, 'fine_amount': 100})
        slip = self.slip()
        self.finance(slip)
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        content = self.wizard(report_type='summary')._generate_xlsx()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            strings = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(item.itertext()) for item in strings]
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            headers = [strings[int(cell.find('s:v', ns).text)]
                       for cell in sheet.findall("s:sheetData/s:row[@r='6']/s:c", ns)]
            for label in ('Salary Type', 'Contract Salary / Rate', 'Gross Salary', 'Payable Days', 'Present Days',
                          'Paid Weekly-off Days', 'Absent Days', 'Public Holiday Days',
                          'Public Holiday Worked Days', 'System Overtime', 'Public Holiday Pay',
                          'Total Earnings', 'System Fine', 'Net Pay Amount'):
                self.assertIn(label, headers)
            values = {cell.attrib['r']: float(cell.find('s:v', ns).text)
                      for cell in sheet.findall("s:sheetData/s:row[@r='7']/s:c", ns)
                      if cell.attrib.get('t') != 's' and cell.find('s:v', ns) is not None}
            self.assertEqual(values['D7'], 9000)
            self.assertEqual(values['N7'], 1.75)
            self.assertEqual(values['O7'], .25)
            self.assertEqual(values['R7'], 200)
            self.assertIsNone(sheet.find('s:sheetViews/s:sheetView/s:pane', ns))

    def test_summary_does_not_invent_monthly_ctc_for_hourly_contract(self):
        self.contract.write({'wage_type': 'hourly', 'hourly_rate': 100})
        self.finance(self.slip())
        data = self.report._data(self.wizard(report_type='summary'))
        row = self.report._employee_summary_rows(data['register'])[0]
        self.assertIsNone(row['ctc'])
        self.assertEqual(row['rate'], 100)

    def test_unified_summary_contains_all_salary_types_and_filter_totals(self):
        self.finance(self.slip())
        for basis in ('hourly', 'daily'):
            employee = self.employee.copy({'name': basis.title() + ' Staff', 'employee_number': False})
            contract = self.contract.copy({'name': basis.title() + ' Contract', 'employee_id': employee.id,
                                           'wage_type': basis, 'hourly_rate': 100, 'daily_wage': 500})
            self.finance(self.slip(employee_id=employee.id, contract_id=contract.id))
        wizard = self.wizard(report_type='summary', employee_ids=[Command.clear()])
        data = self.report._data(wizard)
        grouped = self.report._salary_type_rows(data['register'])
        self.assertEqual([len(grouped[key]) for key in ('monthly', 'hourly', 'daily')], [1, 1, 1])
        with zipfile.ZipFile(io.BytesIO(wizard._generate_xlsx())) as archive:
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            workbook = ET.fromstring(archive.read('xl/workbook.xml'))
            self.assertEqual([item.attrib['name'] for item in workbook.findall('s:sheets/s:sheet', ns)],
                             ['Payslip Summary'])
            detail = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(item.itertext()) for item in shared]
            actual = {}
            for index in range(7, 10):
                cells = {cell.attrib['r']: cell for cell in detail.findall(f"s:sheetData/s:row[@r='{index}']/s:c", ns)}
                salary_type = strings[int(cells[f'C{index}'].find('s:v', ns).text)]
                actual[salary_type] = float(cells[f'D{index}'].find('s:v', ns).text)
                self.assertEqual(float(cells[f'W{index}'].find('s:v', ns).text), 8700)
            self.assertEqual(actual, {'Monthly': 9000, 'Hourly': 100, 'Daily': 500})
            total = detail.find("s:sheetData/s:row/s:c[@r='W11']", ns)
            self.assertEqual(total.find('s:f', ns).text, 'SUBTOTAL(109,W7:W9)')
            self.assertEqual(float(total.find('s:v', ns).text), 26100)
            self.assertIsNone(detail.find("s:sheetData/s:row/s:c[@r='D11']", ns))

    def test_unified_summary_keeps_uncomputed_amounts_blank(self):
        self.slip()
        content = self.wizard(report_type='summary')._generate_xlsx()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            detail = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            net = detail.find("s:sheetData/s:row/s:c[@r='W7']", ns)
            self.assertTrue(net is None or net.find('s:v', ns) is None)

    def test_one_employee_with_two_salary_types_stays_in_both_correct_groups(self):
        self.finance(self.slip(date_to='2026-09-15'))
        hourly = self.contract.copy({'name': 'Hourly Second Half', 'wage_type': 'hourly', 'hourly_rate': 100})
        self.finance(self.slip(date_from='2026-09-16', contract_id=hourly.id))
        data = self.report._data(self.wizard(report_type='summary'))
        grouped = self.report._salary_type_rows(data['register'])
        self.assertEqual(len(grouped['monthly']), 1)
        self.assertEqual(len(grouped['hourly']), 1)
        self.assertEqual(grouped['monthly'][0]['net'], 8700)
        self.assertEqual(grouped['hourly'][0]['net'], 8700)
        self.assertEqual(grouped['daily'], [])

    def test_type_summary_preserves_credit_notes_and_duplicate_resolution(self):
        self.finance(self.slip())
        self.finance(self.slip())
        self.finance(self.slip(credit_note=True))
        data = self.report._data(self.wizard(report_type='summary'))
        self.assertEqual(data['excluded_count'], 1)
        grouped = self.report._salary_type_rows(data['register'])
        self.assertEqual(len(grouped['monthly']), 1)
        self.assertEqual(grouped['monthly'][0]['net'], 0)
        self.assertEqual(grouped['monthly'][0]['payable_days'], 26)

    def test_split_periods_show_rate_once_and_keep_multiple_rates_explicit(self):
        self.contract.write({'wage_type': 'hourly', 'hourly_rate': 100})
        self.finance(self.slip(date_to='2026-09-15'))
        self.finance(self.slip(date_from='2026-09-16'))
        data = self.report._data(self.wizard(report_type='summary'))
        row = self.report._salary_type_rows(data['register'])['hourly'][0]
        self.assertEqual(row['rate'], 100)
        self.assertEqual(row['net'], 17400)
        different = self.contract.copy({'name': 'Different Hourly Contract', 'hourly_rate': 120})
        self.finance(self.slip(contract_id=different.id))
        data = self.report._data(self.wizard(report_type='summary'))
        row = self.report._salary_type_rows(data['register'])['hourly'][0]
        self.assertIsNone(row['rate'])
        self.assertIn('Multiple contract rates', row['issues'])

    def test_zero_hourly_rate_is_a_number_not_missing(self):
        self.contract.write({'wage_type': 'hourly', 'hourly_rate': 0})
        self.finance(self.slip())
        data = self.report._data(self.wizard(report_type='summary'))
        self.assertEqual(self.report._salary_type_rows(data['register'])['hourly'][0]['rate'], 0)

    def test_missing_contract_is_not_silently_classified_as_monthly(self):
        self.slip(contract_id=False)
        with self.assertRaises(UserError):
            self.wizard(report_type='summary')._generate_xlsx()
        self.assertTrue(self.wizard(report_type='review')._generate_xlsx())

    def test_empty_summary_warns_before_returning_download_action(self):
        wizard = self.wizard(report_type='summary')
        with self.assertRaisesRegex(UserError, 'Generate payslips first'):
            wizard.action_download_payslip_excel_report()
        # Direct download requests retain the same validation after a wizard
        # has been opened, so stale URLs cannot produce a misleading workbook.
        with self.assertRaisesRegex(UserError, 'Generate payslips first'):
            wizard._generate_xlsx()

    def test_summary_warning_respects_status_and_period_without_modifying_slips(self):
        slip = self.slip(state='done')
        self.finance(slip)
        wizard = self.wizard(report_type='summary')
        with self.assertRaisesRegex(UserError, 'select Done or All Except Rejected'):
            wizard.action_download_payslip_excel_report()
        wizard.payslip_status = 'done'
        action = wizard.action_download_payslip_excel_report()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['target'], 'download')
        self.assertEqual(action['url'], '/my_excel/download?id=%s' % wizard.id)
        self.assertEqual(slip.state, 'done')
        self.assertEqual(slip.line_ids.filtered(lambda line: line.code == 'NET').total, 8700)
        wizard.write({'start_date': '2026-10-01', 'end_date': '2026-10-31'})
        with self.assertRaisesRegex(UserError, 'No payslips match'):
            wizard.action_download_payslip_excel_report()

    def test_review_can_still_download_missing_payslip_exceptions(self):
        wizard = self.wizard(report_type='review')
        action = wizard.action_download_payslip_excel_report()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))

    def test_legacy_summary_retained_and_empty_selection_explained(self):
        with self.assertRaises(UserError):
            self.wizard(report_type='summary')._generate_xlsx()
        self.finance(self.slip())
        content = self.wizard(report_type='summary')._generate_xlsx()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ET.fromstring(archive.read('xl/workbook.xml'))
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual([item.attrib['name'] for item in root.findall('s:sheets/s:sheet', ns)],
                             ['Payslip Summary'])
            self.assertIn(b'Net Pay Amount', archive.read('xl/sharedStrings.xml'))


    def test_positive_deductions_and_credit_note_follow_saved_net(self):
        slip = self.slip()
        self.finance(slip)
        for line in slip.line_ids.filtered(lambda line: line.code in ('LATE', 'LO')):
            line.amount = -line.amount
        for credit, expected in [(False, 1), (True, -1)]:
            slip.credit_note = credit
            row = self.report._financials(slip)
            self.assertEqual((row['fine'], row['advance'], row['deductions']),
                             (100 * expected, 200 * expected, 300 * expected))
            self.assertEqual(row['earnings'] - row['deductions'], row['net'])

    def test_wage_specific_basic_headers_use_category_and_line_totals(self):
        slip = self.slip()
        base = self.salary(slip, 'BASIC_DAILY', 500, 'BASIC')
        base.quantity = 2
        base.rate = 50
        self.salary(slip, 'BASIC_MONTHLY', 300, 'BASIC')
        gross = self.salary(slip, 'GROSS', 400, 'GROSS')
        gross.quantity = 2
        self.salary(slip, 'NET', 800, 'NET')
        self.assertEqual((slip.basic_pay, slip.gross_pay, slip.net_pay), (800, 800, 800))
        slip.state = 'done'
        saved = [(line.id, line.total) for line in slip.line_ids]
        slip._compute_pay()
        self.assertEqual(saved, [(line.id, line.total) for line in slip.line_ids])
        self.assertEqual(slip.state, 'done')
        base.unlink()
        self.assertEqual(slip.basic_pay, 300)

    def test_summary_allowances_exclude_separately_displayed_ot_and_holiday(self):
        self.finance(self.slip())
        wizard = self.wizard(report_type='summary')
        with zipfile.ZipFile(io.BytesIO(wizard._generate_xlsx())) as archive:
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            monthly = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            value = monthly.find("s:sheetData/s:row/s:c[@r='T7']/s:v", ns)
            self.assertEqual(float(value.text), 500)
            strings = archive.read('xl/sharedStrings.xml')
            self.assertIn(b'Other Allowances', strings)

    def _compact_summary_sheet(self, data):
        output = io.BytesIO()
        with xlsxwriter.Workbook(output, {'in_memory': True}) as workbook:
            self.report._write_salary_summary(workbook, data, self.wizard(report_type='summary'))
        with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(item.itertext()) for item in shared]
        headers = [strings[int(cell.find('s:v', ns).text)]
                   for cell in sheet.findall("s:sheetData/s:row[@r='6']/s:c", ns)]
        def hidden(label):
            index = headers.index(label) + 1
            return any(int(col.get('min')) <= index <= int(col.get('max')) and col.get('hidden') == '1'
                       for col in sheet.findall('s:cols/s:col', ns))
        return sheet, strings, ns, hidden

    def test_compact_summary_hides_only_zero_optional_columns_and_notes(self):
        self.finance(self.slip())
        data = self.report._data(self.wizard(report_type='summary'))
        row = data['register'][0]
        row.update(issues='', holidays=0, holiday_worked=0, public_holiday_pay=0, fine=0,
                   basic=0, earnings=0, net=0, payable_days=0, worked_hours=0)
        sheet, strings, ns, hidden = self._compact_summary_sheet(data)
        for label in ('Public Holiday Days', 'Public Holiday Worked Days', 'Public Holiday Pay',
                      'System Fine', 'Total Work Hours'):
            self.assertTrue(hidden(label), label)
        for label in ('Staff Name', 'Salary Type', 'Contract Salary / Rate', 'Basic',
                      'Gross Salary', 'Net Pay Amount', 'Payable Days'):
            self.assertFalse(hidden(label), label)
        for index in (3, 4, 5):
            self.assertEqual(sheet.find(f"s:sheetData/s:row[@r='{index}']", ns).get('hidden'), '1')
        # Zero-value cells and filter-aware totals are preserved, not deleted.
        self.assertEqual(sheet.find("s:sheetData/s:row/s:c[@r='U7']/s:v", ns).text, '0')
        self.assertEqual(sheet.find("s:sheetData/s:row/s:c[@r='U9']/s:f", ns).text, 'SUBTOTAL(109,U7:U7)')

    def test_compact_summary_keeps_negative_cancelling_and_unknown_columns_visible(self):
        self.finance(self.slip())
        data = self.report._data(self.wizard(report_type='summary'))
        row = data['register'][0]
        row.update(issues='', fine=10, holidays=0, public_holiday_pay=0, worked_hours=0)
        second = dict(row, employee_id=row['employee_id'] + 100000, name='Second employee',
                      fine=-10, holidays=None, public_holiday_pay=25)
        data['register'].append(second)
        sheet, strings, ns, hidden = self._compact_summary_sheet(data)
        self.assertFalse(hidden('System Fine'), 'A zero total must not hide nonzero employee values')
        self.assertFalse(hidden('Public Holiday Days'), 'Unknown is not zero')
        self.assertFalse(hidden('Public Holiday Pay'), 'One nonzero employee keeps the column visible')
        self.assertTrue(hidden('Total Work Hours'))
        self.assertEqual(sheet.find("s:sheetData/s:row/s:c[@r='U10']/s:v", ns).text, '0.0')

    def test_compact_summary_shows_real_review_warnings_without_routine_notes(self):
        self.finance(self.slip())
        data = self.report._data(self.wizard(report_type='summary'))
        data['excluded_count'] = 1
        data['register'][0]['issues'] = 'Pending attendance reviews; Overlapping periods'
        sheet, strings, ns, hidden = self._compact_summary_sheet(data)
        self.assertNotEqual(sheet.find("s:sheetData/s:row[@r='3']", ns).get('hidden'), '1')
        cell = sheet.find("s:sheetData/s:row/s:c[@r='A3']/s:v", ns)
        warning = strings[int(cell.text)]
        self.assertIn('Duplicate payslips excluded: 1', warning)
        self.assertIn('Pending attendance reviews', warning)
        self.assertIn('Overlapping periods', warning)
        self.assertEqual(sheet.find("s:sheetData/s:row[@r='4']", ns).get('hidden'), '1')


@tagged('post_install', '-at_install')
class TestPayrollDownload(HttpCase):
    def test_bad_report_id_returns_400(self):
        self.authenticate('admin', 'admin')
        response = self.url_open('/my_excel/download?id=invalid')
        self.assertEqual(response.status_code, 400)

    def test_download_keeps_salary_private_and_returns_workbook(self):
        employee = self.env['hr.employee'].create({'name': 'HTTP Review Employee', 'company_id': self.env.company.id})
        wizard = self.env['payslip.excel.wizard'].create({'report_type': 'review', 'employee_ids': [Command.set(employee.ids)]})
        user = new_test_user(self.env, login='review_http_user', password='test-password', groups='base.group_user')
        self.authenticate(user.login, 'test-password')
        self.assertEqual(self.url_open('/my_excel/download?id=%s' % wizard.id).status_code, 403)
        self.authenticate('admin', 'admin')
        response = self.url_open('/my_excel/download?id=%s' % wizard.id)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.assertIn('payroll-review-', response.headers['Content-Disposition'])
