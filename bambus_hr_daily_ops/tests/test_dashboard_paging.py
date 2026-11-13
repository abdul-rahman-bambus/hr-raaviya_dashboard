"""Server batching must retain global totals, filters, and complete exports."""
from datetime import datetime
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('-at_install', 'post_install')
class TestDashboardPaging(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.people = cls.env['hr.employee'].create([
            {'name': 'Scroll fixture %03d' % number, 'resource_calendar_id': False}
            for number in range(60)])
        cls.service = cls.env['bambus.attendance.dashboard'].with_context(tz='UTC')

    def read(self, **kwargs):
        return self.service.get_attendance_dashboard('2026-11-12', query='Scroll fixture', **kwargs)

    def test_batches_stable_complete_and_global_metrics(self):
        full = self.read()
        pages = [self.read(offset=offset) for offset in [0, 25, 50]]
        self.assertEqual([len(page['daily_attendance']) for page in pages], [25, 25, 10])
        self.assertEqual([row['id'] for page in pages for row in page['daily_attendance']],
                         [row['id'] for row in full['daily_attendance']])
        for page in pages:
            self.assertEqual(page['metrics'], full['metrics'])
            self.assertEqual(page['paging']['total'], 60)
        self.assertEqual(pages[-1]['paging']['next_offset'], 60)
        self.assertFalse(pages[-1]['paging']['has_more'])
        self.assertEqual(len(self.read(offset=60)['daily_attendance']), 0)

    def test_search_and_status_apply_before_slice(self):
        target = self.people[-1]
        data = self.service.get_attendance_dashboard('2026-11-12', offset=0,
            query=target.name, status_filter='not_marked')
        self.assertEqual([row['id'] for row in data['daily_attendance']], [target.id])
        self.assertEqual(data['paging']['total'], 1)
        data = self.read(offset=0, status_filter='present')
        self.assertEqual(data['paging']['total'], 0)
        data = self.read(offset=0, employee_filter_id=target.id)
        self.assertEqual([row['id'] for row in data['daily_attendance']], [target.id])

    def test_logs_only_for_visible_batch_and_export_skips_logs(self):
        model = type(self.env['bambus.hr.attendance.time.audit'])
        original = model.search
        domains = []
        def capture(records, domain, *args, **kwargs):
            domains.append(domain)
            return original(records, domain, *args, **kwargs)
        with patch.object(model, 'search', capture):
            data = self.read(offset=25)
        expected = [row['id'] for row in data['daily_attendance']]
        self.assertTrue(domains)
        self.assertTrue(all(('employee_id', 'in', expected) in domain for domain in domains))
        domains.clear()
        with patch.object(model, 'search', capture):
            exported = self.read(include_logs=False)
        self.assertEqual(domains, [])
        self.assertEqual(len(exported['daily_attendance']), 60)
        self.assertNotIn('paging', exported)

    def test_invalid_batch_rejected(self):
        for kwargs in [{'offset': -1}, {'offset': 0, 'limit': 0},
                       {'offset': 0, 'limit': 101}, {'offset': True},
                       {'status_filter': 'unknown'}]:
            with self.assertRaises(ValidationError):
                self.read(**kwargs)

    def test_offscreen_fine_review_is_in_server_filter_and_global_totals(self):
        calendar = self.env['resource.calendar'].create({
            'name': 'Scroll late schedule', 'tz': 'UTC',
            'attendance_ids': [Command.clear(), Command.create({
                'name': 'Thursday', 'dayofweek': '3', 'day_period': 'morning',
                'hour_from': 9, 'hour_to': 17})]})
        template = self.env['bambus.attendance.automation.template'].create({
            'name': 'Scroll late rules', 'partial_attendance_salary_treatment': 'fine_only',
            'late_enabled': True, 'late_grace_minutes': 5, 'early_exit_enabled': False,
            'break_enabled': False})
        employee = self.people[-1]
        employee.write({'resource_calendar_id': calendar.id,
                        'attendance_automation_template_id': template.id})
        self.env['hr.contract'].create({'name': 'Scroll late contract',
            'employee_id': employee.id, 'resource_calendar_id': calendar.id,
            'date_start': '2026-01-01', 'wage_type': 'daily', 'wage': 0, 'daily_wage': 885})
        self.env['hr.attendance'].create({'employee_id': employee.id,
            'check_in': datetime(2026, 11, 12, 9, 30)})
        first = self.read(offset=0)
        self.assertNotIn(employee.id, [row['id'] for row in first['daily_attendance']])
        filtered = self.read(offset=0, status_filter='fine_review')
        self.assertEqual([row['id'] for row in filtered['daily_attendance']], [employee.id])
        self.assertEqual(filtered['daily_attendance'][0]['fine_hours'], round(25 / 60, 2))
        self.assertEqual(first['metrics']['fine_review_count'], filtered['metrics']['fine_review_count'])
        self.assertGreaterEqual(first['metrics']['fine_review_count'], 1)
