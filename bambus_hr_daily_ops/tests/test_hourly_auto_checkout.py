"""Opt-in checkout uses real punches and preserves manual/routine audit meaning."""
from datetime import datetime
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('-at_install', 'post_install')
class TestHourlyAutoCheckout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Hourly checkout test', 'hourly_auto_checkout_enabled': True,
            'hourly_auto_checkout_hours': 8})
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Checkout scheduled control', 'tz': 'UTC',
            'attendance_ids': [Command.clear()] + [Command.create({
                'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                'hour_from': 9, 'hour_to': 17}) for day in range(6)]})

    def person(self, wage_type='hourly', scheduled=False, tz='UTC'):
        calendar = self.calendar.id if scheduled else False
        employee = self.env['hr.employee'].create({
            'name': 'Checkout ' + wage_type, 'tz': tz,
            'resource_calendar_id': calendar,
            'attendance_automation_template_id': self.template.id})
        contract = self.env['hr.contract'].create({
            'name': employee.name, 'employee_id': employee.id,
            'resource_calendar_id': calendar, 'date_start': '2026-01-01',
            'wage_type': wage_type, 'wage': 8000, 'hourly_rate': 53, 'daily_wage': 885})
        return employee, contract

    def punch(self, employee, stamp):
        return self.env['hr.attendance'].with_context(
            bambus_attendance_event_source='routine').create({
                'employee_id': employee.id, 'check_in': stamp})

    def run_at(self, stamp, native=False):
        with patch.object(fields.Datetime, 'now', return_value=stamp):
            model = self.env['hr.attendance']
            return (model._cron_auto_check_out() if native
                    else model._cron_hourly_template_auto_check_out())

    def test_elapsed_cutoff_idempotence_and_manual_correction(self):
        employee, _ = self.person()
        punch = self.punch(employee, datetime(2026, 11, 12, 9))
        self.run_at(datetime(2026, 11, 12, 16, 59))
        self.assertFalse(punch.check_out)
        self.run_at(datetime(2026, 11, 12, 17, 4))
        self.assertEqual(punch.check_out, datetime(2026, 11, 12, 17))
        self.assertEqual(punch.out_mode, 'auto_check_out')
        self.assertEqual(punch.worked_hours, 8)
        audits = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id)])
        self.assertEqual(set(audits.mapped('event_source')), {'routine'})
        self.assertEqual(self.run_at(datetime(2026, 11, 12, 18)), 0)
        punch.with_context(bambus_attendance_event_source='manual').write({
            'check_out': datetime(2026, 11, 12, 17, 15)})
        latest = self.env['bambus.hr.attendance.time.audit'].search([
            ('employee_id', '=', employee.id)], order='id desc', limit=1)
        self.assertEqual(latest.event_source, 'manual')

    def test_fixed_time_uses_next_local_cutoff(self):
        self.template.write({'hourly_auto_checkout_basis': 'time', 'hourly_auto_checkout_time': 20})
        employee, _ = self.person(tz='Asia/Calcutta')
        punch = self.punch(employee, datetime(2026, 11, 12, 16))  # 21:30 local
        self.assertEqual(punch._hourly_auto_checkout_deadline(), datetime(2026, 11, 13, 14, 30))
        self.run_at(datetime(2026, 11, 13, 14, 29))
        self.assertFalse(punch.check_out)
        self.run_at(datetime(2026, 11, 13, 14, 31))
        self.assertEqual(punch.check_out, datetime(2026, 11, 13, 14, 30))

    def test_dst_fixed_time(self):
        employee, _ = self.person(tz='America/New_York')
        self.template.write({'hourly_auto_checkout_basis': 'time', 'hourly_auto_checkout_time': 2.5})
        punch = self.punch(employee, datetime(2026, 3, 8, 5))
        self.assertEqual(punch._hourly_auto_checkout_deadline(), datetime(2026, 3, 8, 7, 30))
        punch.write({'check_out': datetime(2026, 3, 8, 7, 30)})
        self.template.hourly_auto_checkout_time = 1.5
        punch = self.punch(employee, datetime(2026, 11, 1, 4))
        self.assertEqual(punch._hourly_auto_checkout_deadline(), datetime(2026, 11, 1, 6, 30))

    def test_only_unscheduled_hourly_and_effective_template(self):
        for wage_type, scheduled in [('hourly', True), ('monthly', False), ('daily', False)]:
            employee, _ = self.person(wage_type, scheduled)
            punch = self.punch(employee, datetime(2026, 11, 12, 9))
            self.assertFalse(punch._hourly_auto_checkout_deadline())
        employee, contract = self.person()
        punch = self.punch(employee, datetime(2026, 11, 12, 9))
        self.template.hourly_auto_checkout_enabled = False
        self.assertFalse(punch._hourly_auto_checkout_deadline())
        self.template.write({'hourly_auto_checkout_enabled': True, 'date_from': '2026-11-13'})
        self.assertFalse(punch._hourly_auto_checkout_deadline())
        self.template.date_from = False
        contract.resource_calendar_id = self.calendar
        self.assertFalse(punch._hourly_auto_checkout_deadline())
        contract.resource_calendar_id = False
        employee.resource_calendar_id = self.calendar
        self.assertFalse(punch._hourly_auto_checkout_deadline())

    def test_native_checkout_stays_scheduled_and_all_writes_are_routine(self):
        self.env.company.write({'auto_check_out': True, 'auto_check_out_tolerance': 1,
                                'resource_calendar_id': self.calendar.id})
        self.template.hourly_auto_checkout_enabled = False
        unscheduled, _ = self.person()
        open_punch = self.punch(unscheduled, datetime(2026, 11, 12, 9))
        for wage_type in ['hourly', 'monthly', 'daily']:
            employee, _ = self.person(wage_type, scheduled=True)
            punch = self.punch(employee, datetime(2026, 11, 12, 9))
            self.run_at(datetime(2026, 11, 12, 23), native=True)
            self.assertEqual(punch.check_out, datetime(2026, 11, 12, 18))
            audits = self.env['bambus.hr.attendance.time.audit'].search([
                ('employee_id', '=', employee.id)])
            self.assertEqual(set(audits.mapped('event_source')), {'routine'})
        self.assertFalse(open_punch.check_out)

    def test_configuration_bounds(self):
        for values in [{'hourly_auto_checkout_hours': 0}, {'hourly_auto_checkout_hours': 25},
                       {'hourly_auto_checkout_basis': 'time', 'hourly_auto_checkout_time': 24}]:
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.template.write(values)
