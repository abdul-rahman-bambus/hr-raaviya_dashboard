"""Render the production OWL components in Chromium with delayed ORM responses.

Run: ODOO_SOURCE=/path/to/odoo python -m unittest discover \
    -s bambus_hr_daily_ops/tests/browser -v
Requires: pip install playwright; Chromium (or CHROMIUM_BIN).
No running Odoo server or database is needed for these UI regression tests.
"""
import os
from pathlib import Path
import re
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2] / 'static/src'
OWL = Path(os.environ['ODOO_SOURCE']) / 'addons/web/static/lib/owl/owl.js'


class DashboardUpdates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'),
            args=['--no-sandbox'],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('http://dashboard.test/**', lambda route: route.fulfill(
            body='<html><body><div id="app"></div></body></html>', content_type='text/html'))
        self.page.goto('http://dashboard.test/')
        self.page.add_script_tag(path=str(OWL))
        self.page.add_script_tag(content='''
            const { Component, onWillStart, useState } = owl;
            const useService = name => owl.useEnv().services[name];
            const registry = { category: () => ({ add() {} }) };
            window.requests = []; window.notifications = [];
            const pending = (...args) => new Promise((resolve, reject) => {
                requests.push({ args, resolve, reject });
            });
            window.services = {
                orm: { call: pending, searchRead: pending },
                action: { doAction() {} },
                notification: { add: (...args) => notifications.push(args) },
            };
            window.employee = id => ({id, name: `Employee ${id}`, department: 'Factory',
                contract_type: 'Monthly', shift: 'Day', status: 'present', logs: [],
                check_in_value: '08:00', check_out_value: '17:00', worked_hours: 8,
                has_attendance: true, fine_enabled: true, overtime_enabled: true});
            window.dailyData = date => ({date, company: 'Test Company', metrics: {},
                daily_attendance: Array.from({length: 25}, (_, i) => employee(i + 1)),
                departments: [], shifts: []});
            window.monthlyData = month => ({month, month_label: month,
                employee: {id: 1, name: 'Employee 1'}, metrics: {}, rows: []});
        ''')
        for name in ('attendance_dashboard', 'attendance_editor', 'employee_attendance', 'employee_dashboard'):
            source = (ROOT / f'js/{name}.js').read_text()
            source = re.sub(r'^import .*;\n', '', source, flags=re.MULTILINE)
            source = source.replace('export class ', 'class ')
            component = {'attendance_dashboard': 'AttendanceDashboard',
                         'attendance_editor': 'AttendanceEditor',
                         'employee_attendance': 'EmployeeAttendance',
                         'employee_dashboard': 'EmployeeDashboard'}[name]
            self.page.add_script_tag(content=source + f'\nwindow.{component} = {component};')
        templates = ''.join((ROOT / f'xml/{name}.xml').read_text().split('<templates xml:space="preserve">')[1].split('</templates>')[0]
                            for name in ('attendance_dashboard', 'attendance_editor', 'employee_attendance', 'employee_dashboard'))
        self.page.evaluate('(templates) => window.templates = templates', '<templates>' + templates + '</templates>')

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [], 'OWL component should render without browser errors')

    def mount(self, component, result):
        self.page.evaluate('''component => {
            window.app = new owl.App(window[component], {templates, env: {services},
                props: {action: {params: {employee_id: 1, selected_date: '2026-10-07'}}}});
            window.mounted = app.mount(document.querySelector('#app')).then(c => window.component = c);
        }''', component)
        self.page.wait_for_function('requests.length === 1')
        self.page.evaluate(f'requests[0].resolve({result})')
        self.page.wait_for_function('window.component && !component.state.loading')

    def tick(self):
        self.page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')

    def test_daily_screens_keep_nodes_focus_and_filters_during_date_change(self):
        for name in ('AttendanceDashboard', 'AttendanceEditor'):
            with self.subTest(component=name):
                if name != 'AttendanceDashboard':
                    self.page.evaluate('app.destroy(); requests.length = 0')
                self.mount(name, "dailyData('2026-10-07')")
                self.page.evaluate('''() => {
                    window.search = document.querySelector('input[type=search]');
                    search.focus(); component.state.query = 'Employee';
                    component.moveDate(1); component.moveDate(1);
                }''')
                self.tick()
                self.assertTrue(self.page.evaluate('search.isConnected && document.activeElement === search'))
                self.assertEqual(self.page.locator('input[type=date]').input_value(), '2026-10-09')
                self.assertEqual(self.page.locator('[role=status]').count(), 1)
                self.assertEqual(self.page.evaluate('requests[2].args[3].selected_date'), '2026-10-09')
                self.page.evaluate("requests[2].resolve(dailyData('2026-10-09'))")
                self.tick()
                self.page.evaluate("requests[1].resolve(dailyData('2026-10-08'))")
                self.tick()
                self.assertEqual(self.page.evaluate('component.state.data.date'), '2026-10-09')
                self.assertTrue(self.page.evaluate('search.isConnected && document.activeElement === search'))
                self.assertEqual(self.page.evaluate('component.state.query'), 'Employee')

    def test_same_date_updates_keep_page_and_errors_keep_content(self):
        self.mount('AttendanceDashboard', "dailyData('2026-10-07')")
        self.page.evaluate('() => { component.state.currentPage = 2; component.load(); }')
        self.page.evaluate("requests[1].resolve(dailyData('2026-10-07'))")
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.currentPage'), 2)
        self.page.evaluate('() => { window.search = document.querySelector("input[type=search]"); component.moveDate(1); }')
        self.page.evaluate('requests[2].reject(new Error("Network unavailable"))')
        self.tick()
        self.assertTrue(self.page.evaluate('search.isConnected'))
        self.assertIn('Showing 2026-10-07', self.page.locator('.alert').inner_text())
        self.page.get_by_text('Try Again', exact=True).click()
        self.assertEqual(self.page.evaluate('requests[3].args[3].selected_date'), '2026-10-08')
        self.page.evaluate("requests[3].resolve(dailyData('2026-10-08'))")
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.currentPage'), 1)

    def test_editor_autosaves_without_rebuilding_rows_and_locks_date(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate('window.row = document.querySelector(".o_bae_employee")')
        self.page.locator('input[title="Punch In"]').first.fill('09:00')
        self.tick()
        self.assertTrue(self.page.locator('input[type=date]').is_disabled())
        self.assertEqual(self.page.evaluate('requests[1].args[2][1]'), '2026-10-07')
        self.assertEqual(self.page.evaluate('requests[1].args[2][2].check_in'), '09:00')
        self.page.evaluate('requests[1].resolve({line_id: 1, worked_hours: 7, status: "present"})')
        self.tick()
        self.assertTrue(self.page.evaluate('row.isConnected'))
        self.assertFalse(self.page.locator('input[type=date]').is_disabled())
        self.assertEqual(self.page.evaluate('requests.length'), 2, 'Autosave should not reload the action')
        self.page.locator('input[type=date]').fill('2026-10-08')
        self.tick()
        self.assertTrue(self.page.locator('input[title="Punch In"]').first.is_disabled())
        self.page.evaluate("requests[2].resolve(dailyData('2026-10-08'))")
        self.tick()
        self.assertFalse(self.page.locator('input[title="Punch In"]').first.is_disabled())

    def test_old_leave_and_adjustment_responses_cannot_update_new_date(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("() => { component.syncEmployee(component.state.data.daily_attendance[0]); component.openAdjustment(component.state.data.daily_attendance[0], 'overtime'); component.moveDate(1); }")
        self.page.evaluate("requests[3].resolve(dailyData('2026-10-08'))")
        self.tick()
        self.page.evaluate("requests[1].resolve({...dailyData('2026-10-07'), metrics: {total: 999}}); requests[2].resolve({wizard_id: 1})")
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.data.date'), '2026-10-08')
        self.assertIsNone(self.page.evaluate('component.state.adjustment'))
        self.assertIsNone(self.page.evaluate('component.state.data.metrics.total ?? null'))

    def test_month_changes_preserve_calendar_and_ignore_old_responses(self):
        self.mount('EmployeeAttendance', "monthlyData('2026-10')")
        self.page.evaluate('component.state.activeView = "calendar"')
        self.tick()
        self.page.evaluate('window.tabs = document.querySelector(".o_bea_tabs"); component.moveMonth(1); component.moveMonth(1)')
        self.tick()
        self.assertTrue(self.page.evaluate('tabs.isConnected'))
        self.assertEqual(self.page.locator('input[type=month]').input_value(), '2026-12')
        self.page.evaluate("requests[2].resolve(monthlyData('2026-12'))")
        self.tick()
        self.page.evaluate('requests[1].reject(new Error("Old request failed"))')
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.data.month'), '2026-12')
        self.assertEqual(self.page.evaluate('component.state.activeView'), 'calendar')
        self.assertEqual(self.page.evaluate('component.state.error'), '')
        self.assertTrue(self.page.evaluate('tabs.isConnected'))

    def test_employee_list_refresh_keeps_filters_selection_and_groups(self):
        self.mount('EmployeeDashboard', '[{id:1, name:"Employee 1", department_id:[1,"Factory"]}]')
        self.page.evaluate('''() => {
            component.state.query = 'Employee'; component.state.selectedIds = [1];
            window.groups = document.querySelector('.o_bed_groups'); component.load();
        }''')
        self.tick()
        self.assertTrue(self.page.evaluate('groups.isConnected'))
        self.page.evaluate('requests[1].reject(new Error("Network unavailable"))')
        self.tick()
        self.assertTrue(self.page.evaluate('groups.isConnected'))
        self.assertEqual(self.page.evaluate('component.state.selectedIds'), [1])
        self.assertEqual(self.page.evaluate('component.state.query'), 'Employee')


if __name__ == '__main__':
    unittest.main()
