"""Date switching batches policy inputs without caching decisions between reads."""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.attendance_read_scope import DashboardReadScope


@tagged('-at_install', 'post_install')
class TestDashboardReadScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.day = fields.Date.to_date('2026-10-22')
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'Read scope calendar', 'tz': 'UTC',
            'attendance_ids': [Command.clear()] + [Command.create({
                'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                'hour_from': 9.75, 'hour_to': 17}) for day in range(6)]})
        cls.template = cls.env['bambus.attendance.automation.template'].create({
            'name': 'Read scope policy', 'partial_attendance_salary_treatment': 'fine_only',
            'late_enabled': True, 'late_grace_minutes': 5,
            'early_exit_enabled': False, 'break_enabled': False})
        cls.people = cls.env['hr.employee'].create([{
            'name': 'Read scope %s' % number, 'resource_calendar_id': cls.calendar.id,
            'attendance_automation_template_id': cls.template.id} for number in range(4)])
        cls.contracts = cls.env['hr.contract'].create([{
            'name': person.name, 'employee_id': person.id, 'date_start': '2026-10-01',
            'resource_calendar_id': cls.calendar.id, 'wage_type': 'daily',
            'wage': 0, 'daily_wage': 885} for person in cls.people])
        cls.punches = cls.env['hr.attendance'].create([{
            'employee_id': person.id, 'check_in': datetime(2026, 10, 22, 9, 51),
            'check_out': datetime(2026, 10, 22, 17)} for person in cls.people])
        cls.service = cls.env['bambus.attendance.dashboard'].with_context(tz='UTC')

    def read(self):
        return self.service.get_attendance_dashboard(self.day, offset=0, query='Read scope')

    def test_detection_uses_batch_instead_of_per_employee_contract_queries(self):
        contract_model = type(self.env['hr.contract'])
        original = contract_model.search
        domains = []
        def capture(records, domain, *args, **kwargs):
            domains.append(domain)
            return original(records, domain, *args, **kwargs)
        with patch.object(contract_model, 'search', capture):
            data = self.read()
        self.assertEqual(len(data['daily_attendance']), 4)
        individual = [domain for domain in domains if any(
            isinstance(term, tuple) and term[:2] == ('employee_id', '=')
            and term[2] in self.people.ids for term in domain)]
        self.assertEqual(individual, [], 'Nested fine/schedule detection must share batched contracts')
        self.assertTrue(any(isinstance(term, tuple) and term[:2] == ('employee_id', 'in')
                            and set(self.people.ids).issubset(term[2])
                            for domain in domains for term in domain))

    def test_later_reads_see_policy_contract_and_punch_changes(self):
        employee = self.people[0]
        def row():
            return next(value for value in self.read()['daily_attendance'] if value['id'] == employee.id)
        self.assertEqual(row()['fine_hours'], round(1 / 60, 2))
        self.template.late_grace_minutes = 0
        self.contracts[0].daily_wage = 900
        self.assertEqual(row()['fine_hours'], .1)
        self.assertEqual(row()['contract_wage_amount'], 900)
        self.punches[0].write({'check_in': datetime(2026, 10, 22, 9, 55)})
        self.assertEqual(row()['fine_hours'], round(10 / 60, 2))
        self.assertNotIn('_bambus_dashboard_read_scope', self.service.env.context)

    def test_outside_scope_uses_normal_historical_contract_resolution(self):
        employee = self.people[0]
        next_day = self.day + timedelta(days=1)
        newer = self.env['hr.contract'].create({
            'name': 'Later dated contract', 'employee_id': employee.id,
            'date_start': next_day, 'wage_type': 'daily', 'wage': 0, 'daily_wage': 999})
        scope = DashboardReadScope(self.day)
        scope.load(employee)
        scoped = employee.with_context(_bambus_dashboard_read_scope=scope)
        self.assertEqual(scoped._get_attendance_contract(self.day), self.contracts[0])
        self.assertEqual(scoped._get_attendance_contract(next_day), newer)
        outside = self.people[1].with_context(_bambus_dashboard_read_scope=scope)
        self.assertEqual(outside._get_attendance_contract(self.day), self.contracts[1])

    def test_client_context_cannot_inject_cached_contracts(self):
        injected = self.people[0].with_context(_bambus_dashboard_read_scope='client supplied')
        self.assertEqual(injected._get_attendance_contract(self.day), self.contracts[0])
        service = self.service.with_context(_bambus_dashboard_read_scope='client supplied')
        self.assertEqual(len(service.get_attendance_dashboard(self.day, query='Read scope')['daily_attendance']), 4)
