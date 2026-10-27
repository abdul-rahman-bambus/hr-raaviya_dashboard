"""Acceptance checks for payroll/reports without any Attendance History model."""
from datetime import datetime

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('-at_install', 'post_install')
class TestIndependentAttendance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.day = fields.Date.to_date('2026-10-22')
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Independent Split Schedule', 'tz': 'UTC',
            'attendance_ids': [Command.clear()] + [Command.create({
                'name': period, 'dayofweek': str(day), 'day_period': period,
                'hour_from': start, 'hour_to': end})
                for day in range(6) for period, start, end in [
                    ('morning', 9.75, 14), ('afternoon', 14.75, 18.75)]],
        })
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Independent Decisions', 'half_day_hours': 3,
            'full_day_basis': 'schedule', 'weekly_off_source': 'weekdays',
            'weekly_off_sunday': True, 'monthly_paid_weekly_off': False,
            'monthly_paid_public_holiday': False, 'late_enabled': False,
            'early_exit_enabled': False, 'break_enabled': False,
            'overtime_enabled': True, 'hourly_pay_enabled': True,
        })
        cls.service = cls.env['bambus.attendance.dashboard'].with_context(tz='UTC')
        rules = []
        for code, category, expression in [
            ('BASIC', 'BASIC', "payslip.total_worker_hours * contract.hourly_rate if contract.wage_type == 'hourly' else payslip.total_regular_pay_amount"),
            ('OT', 'ALW', 'payslip.total_overtime_amount'),
            ('LF', 'DED', '-payslip.total_fine_amount'),
            ('NET', 'NET', 'categories.BASIC + categories.ALW + categories.DED'),
        ]:
            rules.append(cls.env['hr.salary.rule'].create({'name': 'Independent '+code,
                'code': code, 'sequence': len(rules)*10+10,
                'category_id': cls.env.ref('hr_payroll_community.'+category).id,
                'amount_select': 'code', 'amount_python_compute': 'result = '+expression}))
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Independent Structure', 'code': 'INDEPENDENT',
            'rule_ids': [Command.set([r.id for r in rules])]})

    def person(self, basis='daily'):
        employee = self.env['hr.employee'].create({'name': 'Independent '+basis,
            'company_id': self.env.company.id, 'resource_calendar_id': self.calendar.id,
            'attendance_automation_template_id': self.template.id})
        contract = self.env['hr.contract'].create({'name': 'Independent '+basis,
            'employee_id': employee.id, 'resource_calendar_id': self.calendar.id,
            'date_start': '2026-10-01', 'wage_type': basis, 'wage': 8000,
            'daily_wage': 885, 'hourly_rate': 53, 'struct_id': self.structure.id})
        return employee, contract

    def slip(self, employee, contract):
        slip = self.env['hr.payslip'].create({'name': 'Independent payroll',
            'employee_id': employee.id, 'contract_id': contract.id,
            'date_from': self.day, 'date_to': self.day, 'struct_id': self.structure.id})
        slip.action_compute_sheet()
        return slip

    def row(self, employee):
        return next(row for row in self.service.get_attendance_dashboard(str(self.day))[
            'daily_attendance'] if row['id'] == employee.id)

    def test_history_models_are_not_registered_and_dashboard_read_creates_no_review(self):
        self.assertNotIn('bambus.hr.attendance.sheet', self.env)
        self.assertNotIn('bambus.hr.attendance.sheet.line', self.env)
        self.assertNotIn('sheet_id', self.env['bambus.attendance.day.review']._fields)
        employee, contract = self.person()
        self.row(employee)
        self.assertFalse(self.env['bambus.attendance.day.review'].search([
            ('employee_id', '=', employee.id)]))

    def test_manual_time_edits_drive_real_punches_payroll_and_both_exports(self):
        for basis, expected in [('monthly', 129.03), ('daily', 442.5), ('hourly', 159)]:
            with self.subTest(basis=basis):
                employee, contract = self.person(basis)
                self.service.update_dashboard_attendance(employee.id, self.day, {
                    'check_in': '09:45', 'check_out': '12:00', 'status_manual': False})
                punch = self.env['hr.attendance'].search([('employee_id', '=', employee.id)])
                self.assertEqual(len(punch), 1)
                self.assertEqual(punch.worked_hours, 2.25)
                self.service.update_dashboard_attendance(employee.id, self.day, {
                    'check_out': '12:45', 'status_manual': False})
                self.assertEqual(punch.check_out.hour, 12)
                self.assertEqual(punch.worked_hours, 3)
                self.assertEqual(self.row(employee)['worked_hours'], 3)
                slip = self.slip(employee, contract)
                self.assertAlmostEqual(slip.line_ids.filtered(lambda l:l.code=='NET').total, expected, places=2)
                for kind in ('summary', 'review'):
                    wizard = self.env['payslip.excel.wizard'].create({
                        'report_type': kind, 'duration_type': 'custom', 'start_date': self.day,
                        'end_date': self.day, 'employee_ids': [Command.set(employee.ids)]})
                    self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))
                punch.unlink()
                self.assertEqual(self.row(employee)['worked_hours'], 0)
                slip.action_compute_sheet()
                self.assertEqual(slip.line_ids.filtered(lambda l:l.code=='NET').total, 0)

    def test_status_revocation_and_punch_changes_preserve_saved_money(self):
        employee, contract = self.person()
        self.service.update_dashboard_attendance(employee.id,self.day,{
            'check_in':'09:45','check_out':'12:45','status_manual':False})
        review = self.env['bambus.attendance.day.review'].search([('employee_id','=',employee.id)])
        review.write({'fine_state':'approved','fine_hours':.25,'fine_amount':17.88,
            'overtime_state':'approved','overtime_hours':1,'overtime_amount':107.27})
        self.service.update_dashboard_attendance(employee.id,self.day,{'status':'absent'})
        self.service.revoke_dashboard_status(employee.id,self.day,'absent')
        self.service.update_dashboard_attendance(employee.id,self.day,{
            'check_out':'13:45','status_manual':False,'fine_hours':0,'overtime_hours':0})
        self.assertEqual((review.fine_amount,review.overtime_amount),(17.88,107.27))
        self.assertEqual((review.fine_state,review.overtime_state),('approved','approved'))
        self.assertEqual(self.row(employee)['worked_hours'],4)
        slip=self.slip(employee,contract)
        self.assertAlmostEqual(slip.line_ids.filtered(lambda l:l.code=='NET').total,531.89,places=2)

    def test_unchanged_proposal_refresh_does_not_invalidate_open_review(self):
        employee, contract = self.person()
        self.service.update_dashboard_attendance(employee.id, self.day, {
            'check_in': '09:45', 'check_out': '12:45', 'status_manual': False})
        payload = self.service.get_dashboard_review(employee.id, self.day)
        wizard = self.env['bambus.hr.attendance.review.wizard'].browse(payload['wizard_id'])
        review = wizard.line_id
        version = review.write_date
        review._compute_day_data()
        self.assertEqual(review.write_date, version)
        wizard.action_save()

    def test_company_switch_isolates_roster_and_rejects_wrong_company_write(self):
        employee, contract=self.person()
        other=self.env['res.company'].create({'name':'Independent other company'})
        foreign=self.env['hr.employee'].create({'name':'Independent other worker','company_id':other.id})
        both=self.service.with_context(allowed_company_ids=[self.env.company.id,other.id])
        self.assertNotIn(foreign.id,[r['id'] for r in both.get_attendance_dashboard(self.day)['daily_attendance']])
        switched=both.with_company(other)
        self.assertIn(foreign.id,[r['id'] for r in switched.get_attendance_dashboard(self.day)['daily_attendance']])
        self.assertNotIn(employee.id,[r['id'] for r in switched.get_attendance_dashboard(self.day)['daily_attendance']])
        with self.assertRaises(UserError):
            switched.update_dashboard_attendance(employee.id,self.day,{'status':'absent'})

    def test_revoking_status_never_deletes_financial_decisions(self):
        employee,contract=self.person()
        self.service.update_dashboard_attendance(employee.id,self.day,{'status':'absent'})
        review=self.env['bambus.attendance.day.review'].search([('employee_id','=',employee.id)])
        review.write({'fine_state':'rejected','fine_review_data':{'early_pm':{'state':'ignored'}}})
        self.service.revoke_dashboard_status(employee.id,self.day,'absent')
        self.assertTrue(review.exists())
        self.assertFalse(review.attendance_status_manual)
        self.assertEqual(review.fine_review_data,{'early_pm':{'state':'ignored'}})
