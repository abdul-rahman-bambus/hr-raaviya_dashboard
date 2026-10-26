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
        self.tick()

    def tick(self):
        self.page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')

    def test_pencil_opens_selected_employee_day_and_reports_access_errors(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate('() => { window.openedActions = []; services.action.doAction = action => openedActions.push(action); }')
        buttons = self.page.get_by_role('button', name='Open attendance entries', exact=True)
        self.assertEqual(buttons.count(), 25)
        buttons.nth(1).click()
        self.assertEqual(self.page.evaluate('requests[1].args'),
                         ['bambus.hr.attendance.sheet', 'open_dashboard_attendance_entries', [2, '2026-10-07']])
        self.page.evaluate("requests[1].resolve({type: 'ir.actions.act_window', res_model: 'hr.attendance', domain: [['employee_id', '=', 2]]})")
        self.tick()
        self.assertEqual(self.page.evaluate('openedActions[0].res_model'), 'hr.attendance')
        buttons.first.click()
        self.page.evaluate('requests[2].reject(new Error("Access denied"))')
        self.tick()
        self.assertEqual(self.page.evaluate('openedActions.length'), 1)
        self.assertEqual(self.page.evaluate('notifications[0][0]'), 'Access denied')

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

    def test_combined_review_deletes_one_item_and_saves_without_refresh(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate('''() => {
            window.row = document.querySelector('.o_bae_employee');
            component.openAdjustment(component.state.data.daily_attendance[0], 'overtime');
        }''')
        self.assertEqual(self.page.evaluate('requests[1].args[1]'), 'get_dashboard_review')
        self.page.evaluate('''requests[1].resolve({wizard_id: 7, adjustment: 'review',
            employee: 'Employee 1', date: '2026-10-07', daily_rate: 100, hourly_rate: 12.5,
            salary_per_minute: 100/480, currency: {symbol: '₹', position: 'before', decimal_places: 2},
            items: [
                {id: 'overtime', label: 'Overtime', hours: 8, detected_hours: 8,
                 calculation_type: 'salary_1_5', rate: 0, note: '', calculation_options: [['salary_1_5','1.5x Salary']]},
                {id: 1, label: 'Late Fine', hours: 1, detected_hours: 1,
                 calculation_type: 'salary_minute', rate: 0, note: '', calculation_options: [['salary_minute','Per Minute']]},
                {id: 2, label: 'Break / Gap Fine', hours: 1, detected_hours: 1,
                 calculation_type: 'salary_minute', rate: 0, note: '', calculation_options: [['salary_minute','Per Minute']]}
            ]})''')
        self.tick()
        dialog = self.page.get_by_role('dialog')
        self.assertIn('₹ 150.00', dialog.inner_text())
        self.assertEqual(dialog.get_by_role('button', name='Delete / Ignore').count(), 3)
        dialog.get_by_role('button', name='Delete / Ignore').nth(2).click()
        self.tick()
        self.assertEqual(dialog.get_by_role('button', name='Delete / Ignore').count(), 2)
        dialog.get_by_role('button', name='Approve Remaining Items').click()
        self.tick()
        self.assertEqual(self.page.evaluate('requests[2].args[1]'), 'save_dashboard_review')
        self.assertEqual(self.page.evaluate('requests[2].args[2][1].map(item => item.id)'), ['overtime', 1])
        self.page.evaluate('requests[2].resolve({})')
        self.tick()
        self.page.evaluate("requests[3].resolve(dailyData('2026-10-07'))")
        self.tick()
        self.assertTrue(self.page.evaluate('row.isConnected'))
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)

    def test_last_approval_clears_review_filter_and_preserves_date(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            component.state.statusFilter = 'overtime_review';
            component.state.data.daily_attendance[0].overtime_review_pending = true;
            component.state.adjustment = {wizard_id: 1, adjustment: 'review', date: '2026-10-07',
                employee: 'Employee 1', items: [], employeeRecord: component.state.data.daily_attendance[0]};
            component.saveAdjustment();
        }""")
        self.page.evaluate('requests[1].resolve({})')
        self.tick()
        self.page.evaluate("requests[2].resolve(dailyData('2026-10-07'))")
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.statusFilter'), 'all')
        self.assertEqual(self.page.evaluate('component.state.selectedDate'), '2026-10-07')
        self.assertGreater(self.page.locator('.o_bae_employee').count(), 0)

    def test_broad_fine_and_overtime_filters_return_after_last_approval(self):
        for metric in ('fine', 'overtime'):
            with self.subTest(metric=metric):
                if metric == 'overtime':
                    self.page.evaluate('app.destroy(); requests.length = 0')
                self.mount('AttendanceEditor', "dailyData('2026-10-07')")
                self.page.evaluate("""metric => {
                    component.openMetric(metric);
                    const employee = component.state.data.daily_attendance[0];
                    employee[metric + '_hours'] = .25;
                    employee[metric + '_review_pending'] = true;
                    component.state.adjustment = {wizard_id: 1, adjustment: 'review', date: '2026-10-07',
                        employee: 'Employee 1', items: [], employeeRecord: employee};
                    component.saveAdjustment();
                }""", metric)
                self.page.evaluate('requests[1].resolve({})')
                self.tick()
                self.page.evaluate("""metric => {
                    const data = dailyData('2026-10-07');
                    data.daily_attendance[0][metric + '_hours'] = .25;
                    requests[2].resolve(data);
                }""", metric)
                self.tick()
                self.assertEqual(self.page.evaluate('component.state.statusFilter'), 'all')
                self.assertEqual(self.page.evaluate('component.state.selectedDate'), '2026-10-07')
                self.assertEqual(self.page.locator('.o_bae_employee').count(), 25)

    def test_daily_attendance_button_clears_filters_without_changing_date(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            component.openMetric('fine'); component.state.query = 'Employee 1';
            component.state.currentPage = 2;
        }""")
        self.tick()
        self.page.get_by_role('button', name='Daily Attendance', exact=True).click()
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.statusFilter'), 'all')
        self.assertEqual(self.page.evaluate('component.state.query'), '')
        self.assertEqual(self.page.evaluate('component.state.currentPage'), 1)
        self.assertEqual(self.page.evaluate('component.state.selectedDate'), '2026-10-07')
        self.assertEqual(self.page.evaluate('requests.length'), 1)
        self.assertEqual(self.page.get_by_role('button', name='Daily Attendance', exact=True).count(), 0)

    def test_review_moves_to_remaining_fines_instead_of_empty_ot_filter(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            component.state.statusFilter = 'overtime_review';
            component.syncEmployee(component.state.data.daily_attendance[0], '2026-10-07', true);
        }""")
        self.page.evaluate("""() => {
            const data = dailyData('2026-10-07'); data.daily_attendance[0].fine_review_pending = true;
            requests[1].resolve(data);
        }""")
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.statusFilter'), 'fine_review')
        self.assertEqual(self.page.locator('.o_bae_employee').count(), 1)

    def test_half_day_button_opens_confirmation_without_optimistic_leave(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            window.openedActions = [];
            services.action.doAction = (action, options) => openedActions.push({action, options});
            component.createHalfDayLeave(component.state.data.daily_attendance[0]);
        }""")
        self.assertEqual(self.page.evaluate('requests[1].args[1]'), 'create_half_day_leave')
        self.page.evaluate("requests[1].resolve({type: 'ir.actions.act_window', res_model: 'bambus.hr.half.day.leave.wizard', context: {default_period: 'pm'}})")
        self.tick()
        self.assertEqual(self.page.evaluate('openedActions[0].action.context.default_period'), 'pm')
        self.assertEqual(self.page.evaluate('component.state.data.daily_attendance[0].status'), 'present')

    def test_legacy_session_review_opens_proposals_without_saving(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            component.state.adjustment = {wizard_id: 1, adjustment: 'review', date: '2026-10-07',
                employee: 'Employee 1', employeeRecord: component.state.data.daily_attendance[0],
                can_review_sessions: true, items: []};
        }""")
        self.tick()
        self.page.get_by_role('button', name='Review Session Exceptions', exact=True).click()
        self.assertEqual(self.page.evaluate('requests[1].args[2]'), [1, '2026-10-07', True])
        self.page.evaluate("""requests[1].resolve({wizard_id: 2, adjustment: 'review', date: '2026-10-07',
            employee: 'Employee 1', resplit_fines: true, previous_fine_amount: 10, items: [],
            currency: {symbol: '₹', position: 'before', decimal_places: 2}})""")
        self.tick()
        self.assertIn('replaces the previous fine decisions', self.page.get_by_role('dialog').inner_text())
        self.page.get_by_role('button', name='Cancel', exact=True).click()
        self.assertEqual(self.page.evaluate('requests.length'), 2)

    def test_combined_review_scrolls_body_and_keeps_buttons_visible(self):
        self.page.add_style_tag(path=str(ROOT / 'css/attendance_dashboard.css'))
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            component.state.adjustment = {wizard_id: 7, adjustment: 'review',
                employee: 'Employee 1', date: '2026-10-07', daily_rate: 100, hourly_rate: 12.5,
                currency: {symbol: '₹', position: 'before', decimal_places: 2},
                contract_wage_label: 'Monthly Wage', contract_wage_amount: 3000,
                items: ['Overtime', 'Late Fine', 'Break / Gap Fine', 'Early Exit Fine'].map((label, id) => ({
                    id, label, hours: 1, detected_hours: 1, rate: 100, note: '',
                    calculation_type: 'salary_1_5', calculation_options: [['fixed', 'Fixed Amount'], ['salary_1_5', '1.5x Salary']]
                }))};
        }""")
        self.assertIn('Monthly Wage: ₹ 3000.00', self.page.locator('.o_baa_contract_wage').inner_text())
        self.assertTrue(self.page.evaluate("document.querySelector('.o_baa_modal_backdrop').parentElement === document.body"))
        for width, height in ((1366, 600), (1024, 768), (390, 640), (800, 320)):
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.tick()
                bounds = self.page.evaluate("""() => {
                    const modal = document.querySelector('.o_baa_modal');
                    const body = modal.querySelector('.o_baa_body');
                    const header = modal.querySelector('.o_baa_header');
                    const footer = modal.querySelector('.o_baa_footer');
                    const before = [header.getBoundingClientRect().top, footer.getBoundingClientRect().bottom];
                    body.scrollTop = body.scrollHeight;
                    return {top: modal.getBoundingClientRect().top, bottom: modal.getBoundingClientRect().bottom,
                        scrollable: body.scrollHeight > body.clientHeight, scroll: body.scrollTop,
                        overflow: getComputedStyle(body).overflowY,
                        before, after: [header.getBoundingClientRect().top, footer.getBoundingClientRect().bottom]};
                }""")
                self.assertGreaterEqual(bounds['top'], 0)
                self.assertLessEqual(bounds['bottom'], height)
                self.assertEqual(self.page.get_by_role('dialog').locator('select').first.input_value(), 'salary_1_5')
                self.assertTrue(bounds['scrollable'])
                self.assertGreater(bounds['scroll'], 0)
                self.assertEqual(bounds['overflow'], 'auto')
                self.assertEqual(bounds['before'], bounds['after'])
                self.page.get_by_role('button', name='Approve Remaining Items').click(trial=True)

    def test_paid_special_day_labels_render_and_filter_in_editor(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-18')")
        self.page.evaluate('''() => {
            const rows = component.state.data.daily_attendance;
            rows[0].status = 'paid_weekly_off'; rows[0].status_label = 'Paid Weekly Off'; rows[0].has_attendance = false;
            rows[1].status = 'paid_public_holiday'; rows[1].status_label = 'Paid Public Holiday'; rows[1].has_attendance = false;
            component.state.statusFilter = 'paid_weekly_off';
        }''')
        self.tick()
        self.assertEqual(self.page.locator('.o_bae_employee').count(), 1)
        self.assertIn('Paid Weekly Off', self.page.locator('.o_bae_employee_info').inner_text())
        self.assertNotIn('Not Marked', self.page.locator('.o_bae_employee_info').inner_text())
        self.page.evaluate("component.state.statusFilter = 'paid_public_holiday'")
        self.tick()
        self.assertIn('Paid Public Holiday', self.page.locator('.o_bae_employee_info').inner_text())

    def test_withhold_paid_day_requires_reason_updates_immediately_and_can_cancel(self):
        self.mount('AttendanceEditor', "dailyData('2026-10-07')")
        self.page.evaluate("""() => {
            const employee = component.state.data.daily_attendance[0];
            Object.assign(employee, {status: 'paid_weekly_off', status_label: 'Paid Weekly Off',
                has_attendance: false, paid_day_kind: 'weekly_off', paid_day_eligible: true,
                paid_day_withheld: false});
        }""")
        self.tick()
        self.page.get_by_role('button', name='Withhold Paid Day', exact=True).click()
        modal = self.page.get_by_role('dialog')
        self.assertTrue(modal.get_by_role('button', name='Confirm').is_disabled())
        self.assertTrue(self.page.locator('input[type=date]').is_disabled())
        modal.get_by_role('button', name='Cancel').click()
        self.tick()
        self.assertEqual(self.page.evaluate('requests.length'), 1)
        self.page.get_by_role('button', name='Withhold Paid Day', exact=True).click()
        modal.locator('textarea').fill('HR exception')
        modal.get_by_role('button', name='Confirm').click()
        self.tick()
        self.assertEqual(self.page.evaluate('requests[1].args[1]'), 'set_dashboard_paid_day')
        self.assertEqual(self.page.evaluate('requests[1].args[2]'),
                         [1, '2026-10-07', 'weekly_off', 'withhold', 'HR exception'])
        self.page.evaluate("""() => {
            const data = dailyData('2026-10-07');
            Object.assign(data.daily_attendance[0], {status: 'unpaid_weekly_off',
                status_label: 'Unpaid Weekly Off', has_attendance: false,
                paid_day_kind: 'weekly_off', paid_day_eligible: true, paid_day_withheld: true});
            requests[1].resolve(data);
        }""")
        self.tick()
        self.assertEqual(self.page.get_by_role('dialog').count(), 0)
        self.assertIn('Unpaid Weekly Off', self.page.locator('.o_bae_employee_info').first.inner_text())
        self.page.get_by_role('button', name='Restore Paid Day', exact=True).click()
        self.tick()
        self.assertEqual(self.page.evaluate('component.state.paidDayDecision.action'), 'restore')
        self.page.get_by_role('dialog').get_by_role('button', name='Cancel').click()


if __name__ == '__main__':
    unittest.main()
