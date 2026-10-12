from datetime import datetime
import io
import zipfile
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
            'payslip_id': slip.id, 'contract_id': self.contract.id, 'number_of_days': 26., 'number_of_hours': 208.})

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

    def test_multiple_payslips_are_kept_and_overlaps_flagged(self):
        for _ in range(2):
            self.finance(self.slip())
        data = self.report._data(self.wizard())
        self.assertEqual(len(data['register']), 2)
        self.assertTrue(all('Overlapping' in row['issues'] for row in data['register']))
        self.assertEqual(data['summary'][0]['payslips'], 2)
        self.assertEqual(data['summary'][0]['employees'], 1)
        self.assertEqual(data['summary'][0]['net'], 17400)

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
        sheet = self.env['bambus.hr.attendance.sheet'].create({'date': '2026-09-07', 'company_id': self.company.id})
        line = self.env['bambus.hr.attendance.sheet.line'].create({'sheet_id': sheet.id, 'employee_id': self.employee.id,
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
        sheet = self.env['bambus.hr.attendance.sheet'].create({'date': '2026-09-07', 'company_id': self.company.id})
        self.env['bambus.hr.attendance.sheet.line'].create({'sheet_id': sheet.id, 'employee_id': self.employee.id,
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
            self.assertIsNotNone(register.find('s:sheetViews/s:sheetView/s:pane', ns))
            name_cell = register.find("s:sheetData/s:row/s:c[@r='B7']", ns)
            self.assertEqual(name_cell.attrib['t'], 's')
            self.assertIsNone(name_cell.find('s:f', ns))
            net = register.find("s:sheetData/s:row/s:c[@r='AJ7']/s:v", ns)
            self.assertEqual(float(net.text), 8700)
        self.assertEqual(slip.line_ids.filtered(lambda line: line.code == 'NET').total, 8700)

    def test_legacy_summary_retained_and_empty_selection_explained(self):
        with self.assertRaises(UserError):
            self.wizard(report_type='summary')._generate_xlsx()
        self.finance(self.slip())
        content = self.wizard(report_type='summary')._generate_xlsx()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertNotIn('xl/worksheets/sheet2.xml', archive.namelist())
            self.assertIn(b'Net Pay Amount', archive.read('xl/sharedStrings.xml'))


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
