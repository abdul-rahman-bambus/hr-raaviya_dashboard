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

    def test_special_day_worked_fraction_refreshes_above_schedule_without_manual_recompute(self):
        # An 8h assigned schedule must not cap a fixed 9h target forever at .5.
        self.template.write({'full_day_basis': 'fixed', 'full_day_hours': 9})
        from types import SimpleNamespace
        report = (self.env['report.attendance_custom_report.attendance_xlsx']
                  if 'report.attendance_custom_report.attendance_xlsx' in self.env else None)
        for holiday in (False, True):
            with self.subTest(holiday=holiday):
                employee, contract, line = self.worker('monthly')
                if holiday:
                    leave = self.env['resource.calendar.leaves'].create({
                        'name': 'Refresh Test Holiday', 'calendar_id': self.calendar.id,
                        'date_from': '2026-09-27 00:00:00', 'date_to': '2026-09-27 23:59:59'})
                att = line._review_attendances()
                slip = self.slip(employee, contract)
                key = 'holiday_worked' if holiday else 'weekend_worked'
                self.assertEqual(slip[key], .5)
                for checkout, expected, hours in [('18:00:00', 1, 9), ('14:00:00', .5, 5)]:
                    att.check_out = '2026-09-27 ' + checkout
                    self.assertEqual(slip[key], expected)
                    self.assertAlmostEqual(slip.holiday_hours if holiday else slip.weekend_hours, hours)
                    if report is not None:
                        daily = report._compute_employee_daily(employee,
                            SimpleNamespace(date_start=self.day, date_end=self.day), contract=contract)
                        self.assertEqual(daily[self.day]['day_fraction'], expected)
                    slip.action_compute_sheet()
                    code = 'HOLIDAYS' if holiday else 'WEEKEND'
                    self.assertEqual(slip.worked_days_line_ids.filtered(lambda row: row.code == code).number_of_days, expected)
                if holiday:
                    leave.unlink()

    def test_monthly_paid_special_days_keep_base_and_pay_approved_work_separately(self):
        self.template.monthly_paid_public_holiday = True
        for holiday in (False, True):
            with self.subTest(holiday=holiday):
                employee, contract, line = self.worker('monthly', attendance=False)
                if holiday:
                    leave = self.env['resource.calendar.leaves'].create({
                        'name': 'Paid Test Holiday', 'calendar_id': self.calendar.id,
                        'date_from': '2026-09-27 00:00:00', 'date_to': '2026-09-27 23:59:59'})
                slip = self.slip(employee, contract)
                field = 'paid_public_holiday_days' if holiday else 'paid_weekly_off_days'
                self.assertEqual((slip[field], slip.total_regular_pay_amount), (1, 100))
                self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 1)
                att = self.env['hr.attendance'].create({'employee_id': employee.id,
                    'check_in': '2026-09-27 09:00:00', 'check_out': '2026-09-27 13:00:00'})
                line.action_refresh()
                review = self.wizard(line)
                review.action_save()
                slip.action_compute_sheet()
                self.assertEqual((slip[field], slip.total_regular_pay_amount), (1, 100))
                self.assertEqual(slip.holiday_worked if holiday else slip.weekend_worked, .5)
                self.assertEqual(slip.total_public_holiday_amount if holiday else slip.total_overtime_amount, 75)
                self.assertEqual(sum(slip.worked_days_line_ids.mapped('number_of_days')), 1)
                # Removing punches restores a paid day without inventing leave records.
                att.unlink()
                slip.action_compute_sheet()
                self.assertEqual((slip[field], slip.total_regular_pay_amount), (1, 100))
                self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', employee.id)]))
                if holiday:
                    self.assertEqual(slip.paid_weekly_off_days, 0)
                    leave.unlink()

    def test_paid_public_holiday_policy_default_scope_and_effective_fallback(self):
        self.assertFalse(self.template.monthly_paid_public_holiday)
        leave = self.env['resource.calendar.leaves'].create({'name': 'Scoped Paid Holiday',
            'calendar_id': self.calendar.id, 'date_from': '2026-09-27 00:00:00',
            'date_to': '2026-09-27 23:59:59'})
        company = self.template.copy({'name': 'Company Paid Holiday', 'monthly_paid_public_holiday': True})
        self.env.company.attendance_automation_template_id = company
        employee, contract, line = self.worker('monthly', attendance=False)
        slip = self.slip(employee, contract)
        self.assertEqual(slip.paid_public_holiday_days, 0)
        self.template.date_to = '2026-09-26'
        self.assertEqual(slip.paid_public_holiday_days, 1)
        company.active = False
        self.assertEqual(slip.paid_public_holiday_days, 0)
        self.template.write({'date_to': False, 'monthly_paid_public_holiday': True})
        self.assertEqual(slip.paid_public_holiday_days, 1)
        contract.date_start = '2026-09-28'
        self.assertEqual(slip.paid_public_holiday_days, 0)
        for basis in ('daily', 'hourly'):
            employee, contract, line = self.worker(basis, attendance=False)
            self.assertEqual(self.slip(employee, contract).paid_public_holiday_days, 0)

    def test_compute_sheet_refreshes_generated_days_and_preserves_custom_rows(self):
        employee, contract, line = self.worker('monthly', attendance=False)
        slip = self.slip(employee, contract)
        custom = self.env['hr.payslip.worked.days'].create({'name': 'Custom Day Input',
            'code': 'CUSTOM_DAY_INPUT', 'payslip_id': slip.id, 'contract_id': contract.id,
            'number_of_days': .25, 'number_of_hours': 0})
        self.template.monthly_paid_weekly_off = False
        slip.action_compute_sheet()
        self.assertTrue(custom.exists())
        self.assertNotIn('PAID_WEEKLY_OFF', slip.worked_days_line_ids.mapped('code'))
        self.template.monthly_paid_weekly_off = True
        slip.action_compute_sheet()
        self.assertEqual(slip.worked_days_line_ids.filtered(lambda row: row.code == 'PAID_WEEKLY_OFF').number_of_days, 1)

    def regular_worker(self, wage_type='monthly', punches=None):
        day = fields.Date.to_date('2026-09-28')
        self.calendar.attendance_ids = [(5, 0, 0),
            (0, 0, {'name': 'First', 'dayofweek': '0', 'day_period': 'morning', 'hour_from': 9, 'hour_to': 13}),
            (0, 0, {'name': 'Second', 'dayofweek': '0', 'day_period': 'afternoon', 'hour_from': 14, 'hour_to': 18})]
        self.template.write({'reviewed_exception_day_pay': 'regularize', 'full_day_basis': 'schedule',
                             'late_grace_minutes': 5, 'early_exit_enabled': True, 'fine_calculation_type': 'salary_minute'})
        employee, contract, line = self.worker(wage_type, day=day, attendance=False)
        punches = punches if punches is not None else [('09:15', '13:00'), ('14:00', '17:30')]
        for start, end in punches:
            self.env['hr.attendance'].create({'employee_id': employee.id,
                'check_in': '2026-09-28 ' + start + ':00', 'check_out': '2026-09-28 ' + end + ':00'})
        line.action_refresh()
        return employee, contract, line

    def test_reviewed_time_restores_day_pay_without_changing_actual_hours(self):
        from types import SimpleNamespace
        for wage_type in ('monthly', 'daily'):
            with self.subTest(wage_type=wage_type):
                employee, contract, line = self.regular_worker(wage_type)
                atts = line._review_attendances()
                punches = [(att.check_in, att.check_out, att.worked_hours) for att in atts]
                slip = self.slip(employee, contract, line.date)
                self.assertEqual(slip.total_working_days, .5)
                wizard = self.wizard(line)
                self.assertEqual(set(wizard.fine_line_ids.mapped('kind')), {'late_am', 'early_pm'})
                wizard.fine_line_ids.filtered(lambda row: row.kind == 'late_am').unlink()
                wizard.action_save()
                slip.action_compute_sheet()
                self.assertEqual((slip.total_working_days, slip.total_regular_pay_amount), (1, 100))
                self.assertAlmostEqual(slip.total_fine_amount, 6.25)
                self.assertEqual(punches, [(att.check_in, att.check_out, att.worked_hours) for att in atts])
                self.assertEqual(sum(atts.mapped('worked_hours')), 7.25)
                self.assertEqual(line.fine_review_data['late_am']['state'], 'ignored')
                audit = self.env['bambus.hr.attendance.time.audit'].search([('employee_id', '=', employee.id)], limit=1)
                self.assertEqual(audit.exception_decisions, line.fine_review_data)
                if 'report.attendance_custom_report.attendance_xlsx' in self.env:
                    report = self.env['report.attendance_custom_report.attendance_xlsx']
                    daily = report._compute_employee_daily(employee, SimpleNamespace(date_start=line.date, date_end=line.date), contract=contract)
                    self.assertEqual(daily[line.date]['day_fraction'], 1)
                    self.assertEqual(daily[line.date]['worked'], 7.25)
                    self.assertEqual(daily[line.date]['regularized_hours'], .75)
                if 'report.hr_payslip_excel_report.payroll_review' in self.env:
                    export = self.env['payslip.excel.wizard'].create({'report_type': 'summary',
                        'company_id': employee.company_id.id, 'duration_type': 'custom',
                        'start_date': line.date, 'end_date': line.date, 'employee_ids': [(6, 0, employee.ids)]})
                    report = self.env['report.hr_payslip_excel_report.payroll_review']
                    data = report._data(export)
                    self.assertEqual(data['register'][0]['regularized_hours'], .75)
                    self.assertEqual(data['register'][0]['worked_hours'], 7.25)
                    self.assertEqual(data['register'][0]['present'], 1)
                    self.assertEqual(report._employee_summary_rows(data['register'])[0]['regularized_hours'], .75)
                self.template.reviewed_exception_day_pay = 'actual'
                slip.action_compute_sheet()
                self.assertEqual(slip.total_working_days, .5)

    def test_edited_fine_minutes_do_not_manufacture_extra_work_or_excuse_absence(self):
        employee, contract, line = self.regular_worker(punches=[('09:15', '13:00')])
        wizard = self.wizard(line)
        self.assertEqual(wizard.fine_line_ids.mapped('kind'), ['late_am'])
        wizard.fine_line_ids.hours = 10
        wizard.action_save()
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 3.75), 4)
        self.assertEqual(self.slip(employee, contract, line.date).total_working_days, .5)
        # Saved coverage cannot expand after a new earlier checkout.
        line._review_attendances().check_out = '2026-09-28 12:00:00'
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 2.75), 3)
        line._review_attendances().unlink()
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 0), 0)
        self.env['hr.attendance'].create({'employee_id': employee.id,
            'check_in': '2026-09-28 14:00:00', 'check_out': '2026-09-28 15:00:00'})
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 1), 1)

    def test_ignored_components_are_persistent_and_cancel_has_no_effect(self):
        employee, contract, line = self.regular_worker()
        wizard = self.wizard(line)
        wizard.fine_line_ids.unlink()
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)
        wizard.action_save()
        line.action_refresh()
        self.assertFalse(self.wizard(line).fine_line_ids)
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 8)
        self.assertEqual(self.slip(employee, contract, line.date).total_fine_amount, 0)

    def test_stale_punch_review_cannot_save(self):
        employee, contract, line = self.regular_worker()
        wizard = self.wizard(line)
        line._review_attendances()[0].check_in = '2026-09-28 09:20:00'
        with self.assertRaises(UserError):
            wizard.action_save()

    def test_half_leave_suggests_opposite_session_and_requires_confirmation(self):
        for punches, expected in [([('09:00', '13:00')], 'pm'),
                                  ([('14:00', '18:00')], 'am'),
                                  ([('09:00', '13:00'), ('14:00', '18:00')], False), ([], False)]:
            employee, contract, line = self.regular_worker(punches=punches)
            action = self.env['bambus.hr.attendance.sheet'].create_half_day_leave(employee.id, line.date)
            self.assertEqual(action['context']['default_period'], expected)
            self.assertFalse(self.env['hr.leave'].search([('employee_id', '=', employee.id)]))

    def test_salary_multiplier_detail_explains_saved_amount_after_wage_change(self):
        employee, contract, line = self.worker('monthly')
        self.wizard(line).action_save()
        original = line.overtime_amount
        contract.wage = 6000
        slip = self.slip(employee, contract)
        detail = slip.attendance_earning_detail_ids
        self.assertEqual(detail.calculation_type, 'salary_1_5')
        self.assertAlmostEqual(detail.rate * detail.hours, original)
        self.assertEqual(detail.rate_unit, 'per hour')
        self.assertAlmostEqual(line.overtime_amount, original)

    def test_half_day_leave_paid_and_unpaid_follow_normal_approval(self):
        for wage_type in ('monthly', 'daily'):
            for paid in (True, False):
                with self.subTest(wage_type=wage_type, paid=paid):
                    employee, contract, line = self.regular_worker(wage_type, punches=[('09:00', '13:00')])
                    leave_type = self.env['hr.leave.type'].create({'name': 'Half Paid' if paid else 'Half Unpaid',
                        'request_unit': 'half_day', 'requires_allocation': 'no', 'unpaid': not paid,
                        'leave_validation_type': 'hr'})
                    action = self.env['bambus.hr.attendance.sheet'].prepare_half_day_leave(employee.id, line.date)
                    wizard = self.env[action['res_model']].with_context(**action['context']).create({'leave_type_id': leave_type.id})
                    wizard.action_confirm()
                    leave = self.env['hr.leave'].search([('employee_id', '=', employee.id)])
                    self.assertEqual(leave.state, 'confirm')
                    self.assertEqual(leave.request_date_from_period, 'pm')
                    slip = self.slip(employee, contract, line.date)
                    self.assertEqual(slip.total_regular_pay_amount, 50)
                    leave.action_approve()
                    if leave.state != 'validate':
                        leave.action_validate()
                    slip.action_compute_sheet()
                    self.assertEqual(slip.total_regular_pay_amount, 100 if paid else 50)
                    self.assertEqual(sum(line._review_attendances().mapped('worked_hours')), 4)

    def test_hourly_does_not_receive_reviewed_day_credit(self):
        employee, contract, line = self.regular_worker('hourly')
        self.assertIsNone(employee._attendance_exception_components(line.date))
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)
        self.assertAlmostEqual(self.slip(employee, contract, line.date).total_regular_pay_amount, 7.25 * 12.5)

    def test_legacy_fine_decisions_are_not_doubled_or_given_guessed_coverage(self):
        employee, contract, line = self.regular_worker()
        line.write({'fine_state': 'approved', 'fine_hours': .5, 'fine_amount': 10,
                    'fine_review_data': {'late': {'state': 'approved', 'hours': .5,
                        'amount': 10, 'calculation_type': 'fixed', 'rate': 10}}})
        review = self.wizard(line)
        self.assertEqual(review.fine_line_ids.mapped('kind'), ['late'])
        review.action_save()
        self.assertEqual(line.fine_amount, 10)
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)

    def test_approved_fine_components_retain_independent_methods_in_payslip(self):
        employee, contract, line = self.regular_worker()
        review = self.wizard(line)
        late = review.fine_line_ids.filtered(lambda row: row.kind == 'late_am')
        late.write({'hours': .1, 'calculation_type': 'fixed', 'rate': 3})
        review.action_save()
        slip = self.slip(employee, contract, line.date)
        details = slip.attendance_deduction_detail_ids
        self.assertEqual(set(details.mapped('calculation_type')), {'fixed', 'salary_minute'})
        per_minute = details.filtered(lambda row: row.calculation_type == 'salary_minute')
        self.assertEqual(per_minute.rate_unit, 'per minute')
        self.assertEqual(line.currency_id.round(per_minute.rate * per_minute.hours * 60), per_minute.amount)
        self.assertAlmostEqual(sum(details.mapped('amount')), slip.total_fine_amount)
        self.assertEqual(slip.total_working_days, 1)

    def test_day_credit_respects_effective_template_and_special_dates(self):
        employee, contract, line = self.regular_worker()
        review = self.wizard(line)
        review.fine_line_ids.unlink()
        review.action_save()
        company_template = self.template.copy({'name': 'Reviewed Company Fallback'})
        self.env.company.attendance_automation_template_id = company_template
        self.template.date_from = '2026-10-01'
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 8)
        company_template.reviewed_exception_day_pay = 'actual'
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)
        company_template.reviewed_exception_day_pay = 'regularize'
        company_template.write({'weekly_off_sunday': False, 'weekly_off_monday': True})
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)
        company_template.weekly_off_monday = False
        holiday = self.env['resource.calendar.leaves'].create({'name': 'Reviewed Holiday',
            'calendar_id': self.calendar.id, 'date_from': '2026-09-28 00:00:00', 'date_to': '2026-09-28 23:59:59'})
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)
        holiday.unlink()
        contract.date_start = '2026-10-01'
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)

    def test_unreviewed_seconds_do_not_get_implicit_tolerance(self):
        employee, contract, line = self.regular_worker(punches=[('09:00', '13:00'), ('14:00', '18:00')])
        line._review_attendances()[0].check_in = '2026-09-28 09:00:03'
        actual = sum(line._review_attendances().mapped('worked_hours'))
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, actual), actual)
        self.assertLess(actual, 8)
        self.assertEqual(self.slip(employee, contract, line.date).total_working_days, .5)

    def test_day_credit_excludes_leave_intervals_and_open_punches(self):
        employee, contract, line = self.regular_worker()
        self.wizard(line).action_save()
        leave_type = self.env['hr.leave.type'].create({'name': 'Reviewed Unpaid Half',
            'request_unit': 'half_day', 'requires_allocation': 'no', 'unpaid': True})
        self.env['hr.leave'].create({'employee_id': employee.id, 'holiday_status_id': leave_type.id,
            'request_date_from': line.date, 'request_date_to': line.date,
            'request_unit_half': True, 'request_date_from_period': 'pm'})
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.5)
        line._review_attendances()[-1].check_out = False
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)

    def test_half_leave_inference_uses_calendar_period_not_punch_order_or_noon(self):
        employee, contract, line = self.regular_worker(punches=[('12:00', '13:00')])
        morning = self.calendar.attendance_ids.filtered(lambda rule: rule.day_period == 'morning')
        morning.hour_to = 11
        self.calendar.attendance_ids = [(0, 0, {'name': 'Later Morning', 'dayofweek': '0',
            'day_period': 'morning', 'hour_from': 11, 'hour_to': 13})]
        action = self.env['bambus.hr.attendance.sheet'].prepare_half_day_leave(employee.id, line.date)
        self.assertEqual(action['context']['default_period'], 'pm')

    def test_legacy_session_reassessment_requires_new_approval_and_keeps_previous_audit(self):
        employee, contract, line = self.regular_worker()
        line.write({'fine_state': 'approved', 'fine_hours': .5, 'fine_amount': 10,
                    'overtime_state': 'approved', 'overtime_hours': 1, 'overtime_amount': 75,
                    'fine_calculation_type': 'fixed', 'fine_rate': 10,
                    'fine_review_data': {'late': {'state': 'approved', 'hours': .5,
                        'amount': 10, 'calculation_type': 'fixed', 'rate': 10}}})
        dashboard = self.env['bambus.hr.attendance.sheet']
        current = dashboard.get_dashboard_review(employee.id, line.date)
        self.assertTrue(current['can_review_sessions'])
        payload = dashboard.get_dashboard_review(employee.id, line.date, True)
        self.assertTrue(payload['resplit_fines'])
        self.assertEqual({item['label'] for item in payload['items']}, {'First Half: Late Entry', 'Second Half: Early Exit'})
        self.assertEqual(line.fine_amount, 10)  # Opening/Cancel does not replace approval.
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 7.25)
        dashboard.save_dashboard_review(payload['wizard_id'], [])
        self.assertEqual(line.fine_state, 'rejected')
        self.assertEqual(line.fine_amount, 0)
        self.assertEqual((line.overtime_state, line.overtime_hours, line.overtime_amount), ('approved', 1, 75))
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 8)
        audit = self.env['bambus.hr.attendance.time.audit'].search([('employee_id', '=', employee.id)], limit=1)
        self.assertEqual(audit.previous_fine_review['amount'], 10)
        self.assertIn('late', audit.previous_fine_review['decisions'])
        self.assertFalse(dashboard.get_dashboard_review(employee.id, line.date)['can_review_sessions'])

    def test_split_morning_review_components_stay_in_first_half(self):
        employee, contract, line = self.regular_worker(punches=[])
        morning = self.calendar.attendance_ids.filtered(lambda rule: rule.day_period == 'morning')
        morning.hour_to = 11
        self.calendar.attendance_ids = [(0, 0, {'name': 'Later Morning', 'dayofweek': '0',
            'day_period': 'morning', 'hour_from': 11, 'hour_to': 13})]
        for start, end in [('09:15', '10:45'), ('11:15', '13:00'), ('14:00', '18:00')]:
            self.env['hr.attendance'].create({'employee_id': employee.id,
                'check_in': '2026-09-28 ' + start + ':00', 'check_out': '2026-09-28 ' + end + ':00'})
        line.action_refresh()
        review = self.wizard(line)
        self.assertEqual(set(review.fine_line_ids.mapped('kind')), {'late_am', 'early_am'})
        review.fine_line_ids.unlink()
        review.action_save()
        self.assertEqual(employee._get_attendance_day_pay_hours(line.date, 7.25), 8)
