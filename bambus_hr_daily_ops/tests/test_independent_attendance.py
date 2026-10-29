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

    def revision_case(self):
        self.template.write({'late_enabled': True, 'late_grace_minutes': 0,
                             'fine_calculation_type': 'salary_minute',
                             'overtime_rate': 120, 'overtime_calculation_type': 'fixed_hour'})
        employee, contract = self.person()
        am = self.env['hr.attendance'].create({'employee_id': employee.id,
            'check_in': datetime(2026, 10, 22, 9, 55), 'check_out': datetime(2026, 10, 22, 14)})
        pm = self.env['hr.attendance'].create({'employee_id': employee.id,
            'check_in': datetime(2026, 10, 22, 14, 45), 'check_out': datetime(2026, 10, 22, 19, 45)})
        payload = self.service.get_dashboard_review(employee.id, self.day)
        wizard = self.env['bambus.hr.attendance.review.wizard'].browse(payload['wizard_id'])
        self.assertTrue(wizard.fine_line_ids)
        wizard.fine_line_ids.write({'calculation_type': 'fixed', 'rate': 100})
        wizard.write({'calculation_type': 'fixed_hour', 'rate': 120})
        wizard.action_save()
        review = wizard.line_id
        self.assertEqual(review.fine_amount, 100)
        self.assertEqual(review.overtime_state, 'approved')
        self.assertEqual(review.overtime_amount, 120)
        return employee, contract, am, pm, review

    def test_punch_correction_supersedes_fine_and_zero_can_be_reapproved(self):
        employee, contract, am, pm, review = self.revision_case()
        slip = self.slip(employee, contract)
        saved_lines = sorted((line.id, line.total) for line in slip.line_ids)
        ot = (review.overtime_state, review.overtime_amount)
        old = self.service.get_dashboard_review(employee.id, self.day)
        am.write({'check_in': datetime(2026, 10, 22, 9, 45)})
        with self.assertRaises(UserError):
            # A pre-edit popup cannot approve a stale proposal.
            self.env['bambus.hr.attendance.review.wizard'].browse(old['wizard_id']).action_save()
        self.assertTrue(review.fine_re_review_required)
        self.assertEqual((review.fine_state, review.fine_hours, review.fine_amount), ('submitted', 0, 0))
        self.assertEqual((review.overtime_state, review.overtime_amount), ot)
        row = self.row(employee)
        self.assertTrue(row['fine_review_pending'])
        self.assertEqual(row['fine_hours'], 0)
        self.assertTrue(any('requires re-review' in log.get('details', '') for log in row['logs']))
        self.assertEqual(sorted((line.id, line.total) for line in slip.line_ids), saved_lines)
        with self.assertRaises(UserError):
            slip.action_compute_sheet()
        with self.assertRaises(UserError):
            slip.action_payslip_done()
        audit = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id), ('previous_review', '!=', False)], order='id desc', limit=1)
        self.assertEqual(audit.previous_review['amount'], 100)
        self.assertEqual(audit.current_proposal['hours'], 0)
        payload = self.service.get_dashboard_review(employee.id, self.day)
        fresh = self.env['bambus.hr.attendance.review.wizard'].browse(payload['wizard_id'])
        self.assertEqual(len(fresh.fine_line_ids), 1)
        self.assertEqual(fresh.fine_line_ids.amount, 0)
        fresh.action_save()
        self.assertFalse(review.fine_re_review_required)
        slip.action_compute_sheet()
        self.assertEqual(slip.total_fine_amount, 0)
        first_net = slip.line_ids.filtered(lambda row: row.code == 'NET').total
        slip.action_compute_sheet()
        self.assertEqual(slip.line_ids.filtered(lambda row: row.code == 'NET').total, first_net)

    def test_checkout_correction_supersedes_ot_but_preserves_fine(self):
        employee, contract, am, pm, review = self.revision_case()
        fine = (review.fine_state, review.fine_amount, review.fine_review_data)
        pm.write({'check_out': datetime(2026, 10, 22, 18, 45)})
        self.assertTrue(review.overtime_re_review_required)
        self.assertEqual(review.overtime_state, 'submitted')
        self.assertEqual(review.overtime_hours, 0)
        self.assertEqual((review.fine_state, review.fine_amount, review.fine_review_data), fine)
        payload = self.service.get_dashboard_review(employee.id, self.day)
        fresh = self.env['bambus.hr.attendance.review.wizard'].browse(payload['wizard_id'])
        self.assertTrue(fresh.show_overtime)
        self.assertEqual(fresh.overtime_amount, 0)
        fresh.action_save()
        self.assertFalse(review.overtime_re_review_required)
        self.assertEqual(review.overtime_amount, 0)

    def test_noop_or_metadata_edit_does_not_supersede_or_duplicate_audit(self):
        employee, contract, am, pm, review = self.revision_case()
        Audit = self.env['bambus.hr.attendance.time.audit']
        domain = [('employee_id', '=', employee.id)]
        count = Audit.search_count(domain)
        am.write({'check_in': am.check_in, 'check_out': am.check_out})
        am.write({'bambus_gap_minutes': am.bambus_gap_minutes})
        self.row(employee)
        self.assertEqual(Audit.search_count(domain), count)
        self.assertFalse(review.fine_re_review_required or review.overtime_re_review_required)

    def test_deleting_punch_supersedes_affected_ot_with_full_punch_audit(self):
        employee, contract, am, pm, review = self.revision_case()
        punch_id = pm.id
        pm.unlink()
        self.assertTrue(review.overtime_re_review_required)
        audit = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id), ('adjustment_type', '=', 'attendance')], order='id desc', limit=1)
        self.assertEqual(audit.punch_changes['operation'], 'deleted')
        self.assertEqual(audit.punch_changes['before'][0]['id'], punch_id)
        self.assertEqual(audit.punch_changes['after'], [])

    def test_punch_correction_keeps_finalized_salary_snapshot_unchanged(self):
        employee, contract, am, pm, review = self.revision_case()
        slip = self.slip(employee, contract)
        slip.action_payslip_done()
        saved = [(line.id, line.total) for line in slip.line_ids]
        am.write({'check_in': datetime(2026, 10, 22, 9, 45)})
        self.assertEqual(slip.state, 'done')
        self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
        self.assertTrue(review.fine_re_review_required)

    def test_excluded_fine_needs_review_if_punch_change_introduces_new_lateness(self):
        employee, contract, am, pm, review = self.revision_case()
        review.write({'fine_state': 'rejected', 'fine_hours': 0, 'fine_amount': 0})
        am.write({'check_in': datetime(2026, 10, 22, 10, 15)})
        self.assertTrue(review.fine_re_review_required)
        self.assertEqual(review.fine_state, 'submitted')
        payload = self.service.get_dashboard_review(employee.id, self.day)
        fresh = self.env['bambus.hr.attendance.review.wizard'].browse(payload['wizard_id'])
        fresh.fine_line_ids.write({'calculation_type': 'fixed', 'rate': 50})
        fresh.action_save()
        self.assertFalse(review.fine_re_review_required)
        self.assertEqual(review.fine_amount, 50)

    def test_extra_session_creation_and_date_move_invalidate_correct_day(self):
        employee, contract, am, pm, review = self.revision_case()
        extra = self.env['hr.attendance'].create({'employee_id': employee.id,
            'check_in': datetime(2026, 10, 22, 20), 'check_out': datetime(2026, 10, 22, 21)})
        self.assertTrue(review.overtime_re_review_required)
        fresh = self.env['bambus.hr.attendance.review.wizard'].browse(
            self.service.get_dashboard_review(employee.id, self.day)['wizard_id'])
        fresh.action_save()
        extra.write({'check_in': datetime(2026, 10, 23, 20), 'check_out': datetime(2026, 10, 23, 21)})
        self.assertTrue(review.overtime_re_review_required)
        audits = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id), ('adjustment_type', '=', 'attendance'),
            ('date', 'in', [self.day, fields.Date.to_date('2026-10-23')])])
        self.assertEqual(set(audits.mapped('date')), {self.day, fields.Date.to_date('2026-10-23')})

    def test_review_cancel_keeps_correction_pending_and_log_snapshot(self):
        employee, contract, am, pm, review = self.revision_case()
        am.with_context(attendance_change_reason='Corrected mistyped arrival').write({
            'check_in': datetime(2026, 10, 22, 9, 45)})
        payload = self.service.get_dashboard_review(employee.id, self.day)
        self.assertTrue(payload['re_review_required'])
        self.env['bambus.hr.attendance.review.wizard'].browse(payload['wizard_id']).unlink()
        self.assertTrue(review.fine_re_review_required)
        audit = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id), ('previous_review', '!=', False)], limit=1)
        self.assertEqual(audit.previous_review['amount'], 100)
        self.assertIn('Corrected mistyped arrival', audit.change_details)
        self.assertEqual(audit.updated_by_id, self.env.user)

    def test_audit_evidence_is_append_only(self):
        employee, contract, am, pm, review = self.revision_case()
        audit = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id)], limit=1)
        with self.assertRaises(UserError):
            audit.write({'adjusted_hours': 100})
        with self.assertRaises(UserError):
            audit.unlink()

    def test_zero_correction_remains_reviewable_when_detection_rule_is_disabled(self):
        employee, contract, am, pm, review = self.revision_case()
        self.template.late_enabled = False
        am.write({'check_in': datetime(2026, 10, 22, 9, 45)})
        self.assertTrue(review.fine_re_review_required)
        self.assertTrue(self.row(employee)['fine_enabled'])
        fresh = self.env['bambus.hr.attendance.review.wizard'].browse(
            self.service.get_dashboard_review(employee.id, self.day)['wizard_id'])
        self.assertEqual(fresh.fine_line_ids.amount, 0)
        fresh.action_save()
        self.assertFalse(review.fine_re_review_required)
