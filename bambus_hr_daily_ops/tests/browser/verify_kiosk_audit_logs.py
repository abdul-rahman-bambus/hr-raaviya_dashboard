"""Installed kiosk endpoint -> clean Logs -> manual dashboard edit; test DB only."""
import argparse
import os
import re
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('An isolated test database is required.')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'), args=['--no-sandbox'])
        context = browser.new_context()
        auth = context.request.post(args.url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert auth.get('result', {}).get('uid'), 'Test login failed'
        created = []

        def rpc(model, method, values, kwargs=None):
            result = context.request.post(args.url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {'model': model,
                    'method': method, 'args': values, 'kwargs': kwargs or {'context': {'tz': 'UTC'}}}}).json()
            assert 'error' not in result, result.get('error', {}).get('data', {}).get('message')
            return result['result']

        def create(model, values):
            record = rpc(model, 'create', [values])
            created.append((model, record))
            return record

        try:
            calendar = create('resource.calendar', {'name': 'Log Source Browser Calendar', 'tz': 'UTC',
                'attendance_ids': [(5, 0, 0), (0, 0, {'name': 'Thursday', 'dayofweek': '3',
                    'day_period': 'morning', 'hour_from': 9, 'hour_to': 17})]})
            template = create('bambus.attendance.automation.template', {'name': 'Log Source Browser Template',
                'late_enabled': False, 'break_enabled': False, 'early_exit_enabled': False})
            employee = create('hr.employee', {'name': 'Log Source Browser Employee',
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            create('hr.contract', {'name': 'Log Source Browser Contract', 'employee_id': employee,
                'date_start': '2026-10-01', 'resource_calendar_id': calendar,
                'wage_type': 'daily', 'daily_wage': 885, 'wage': 0})
            company = auth['result']['user_companies']['current_company']

            def kiosk(values):
                result = context.request.post(args.url + '/face_attendance', data={
                    'jsonrpc': '2.0', 'method': 'call', 'params': dict(company_id=company, **values)}).json()
                assert 'error' not in result, result
                return result['result']

            # Exercise the real face sync route, including requests without modes.
            first = kiosk({'create_attendance': [{'employee_id': employee,
                'check_in': '2026-10-22 09:45:00'}]})['new_attendance_ids'][0]
            created.append(('hr.attendance', first))
            kiosk({'update_attendance': [{'odoo_id': first, 'check_out': '2026-10-22 14:00:00'}]})
            second = kiosk({'create_attendance': [{'employee_id': employee,
                'check_in': '2026-10-22 14:45:00'}]})['new_attendance_ids'][0]
            created.append(('hr.attendance', second))

            def dashboard_row():
                return next(row for row in rpc('bambus.attendance.dashboard', 'get_attendance_dashboard',
                            ['2026-10-22'])['daily_attendance'] if row['id'] == employee)

            row = dashboard_row()
            assert len(row['logs']) == 3 and not any(item['type'] == 'hr_update' for item in row['logs']), row['logs']
            audits = rpc('bambus.hr.attendance.time.audit', 'search_read', [[['employee_id', '=', employee]]],
                         {'fields': ['event_source']})
            assert len(audits) == 3 and all(item['event_source'] == 'routine' for item in audits), audits
            rpc('bambus.attendance.dashboard', 'update_dashboard_attendance',
                [employee, '2026-10-22', {'check_in': '09:50', 'status_manual': False}])
            row = dashboard_row()
            assert len([item for item in row['logs'] if item['type'] == 'hr_update']) == 1, row['logs']
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({type:'ir.actions.client',
                tag:'bambus_attendance_editor', params:{selected_date:'2026-10-22'}})""")
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Log Source Browser Employee')
            card = page.locator('.o_bae_employee').filter(has_text='Log Source Browser Employee')
            expect(card).to_be_visible()
            card.get_by_role('button', name=re.compile('Logs')).click()
            logs = page.locator('.o_bea_log_modal')
            expect(logs).to_be_visible()
            expect(logs).to_contain_text('Attendance time adjusted')
            assert logs.inner_text().count('via HR Update') == 1, logs.inner_text()
            assert not errors, errors
            # A legacy record with no corroborated photo must not crash the list-based
            # dashboard caller or be silently hidden as a routine event.
            legacy = rpc('bambus.hr.attendance.time.audit', 'create', [{
                'employee_id': employee, 'date': '2026-10-22', 'adjustment_type': 'attendance',
                'event_source': 'legacy', 'punch_changes': {'operation': 'created', 'before': [],
                    'after': [{'id': first, 'employee_id': employee,
                               'check_in': '2026-10-22 09:45:00', 'check_out': False}]}}])
            assert any(item['id'] == 'hr-%s' % legacy for item in dashboard_row()['logs'])
            print('PASS: kiosk punches deduplicated, manual edit logged once, legacy audit dashboard request succeeds and ambiguous evidence remains visible.')
        finally:
            for model, record in reversed(created):
                if model == 'hr.employee':
                    reviews = rpc('bambus.attendance.day.review', 'search', [[['employee_id', '=', record]]])
                    if reviews:
                        rpc('bambus.attendance.day.review', 'unlink', [reviews])
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
