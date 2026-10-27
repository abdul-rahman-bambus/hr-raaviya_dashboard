"""Verify each daily-card pencil opens only that employee's selected-day punches.

Run on an isolated test DB with Playwright/Chromium:
python bambus_hr_daily_ops/tests/browser/verify_attendance_entry_navigation.py \
    --url http://localhost:8071 --db YOUR_TEST_DATABASE
Fixtures are removed. No existing punches or approvals are edited.
"""
import argparse
from datetime import datetime
import os
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('Use an isolated database containing test in its name.')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'),
            args=['--no-sandbox'])
        context = browser.new_context()
        url = args.url.rstrip('/')
        auth = context.request.post(url + '/web/session/authenticate', data={'jsonrpc': '2.0',
            'method': 'call', 'params': {'db': args.db, 'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        session = auth.get('result', {})
        assert session.get('uid'), 'Test authentication failed'
        timezone = ZoneInfo(session.get('user_context', {}).get('tz') or 'UTC')

        def rpc(model, method, values, kwargs=None):
            result = context.request.post(url + '/web/dataset/call_kw', data={'jsonrpc': '2.0',
                'method': 'call', 'params': {'model': model, 'method': method, 'args': values,
                    'kwargs': kwargs or {}}}).json()
            assert 'error' not in result, result.get('error', {}).get('data', {}).get('message')
            return result['result']

        created = []
        def create(model, values):
            record = rpc(model, 'create', [values])
            created.append((model, record))
            return record

        def utc(value):
            return datetime.fromisoformat(value).replace(tzinfo=timezone).astimezone(
                ZoneInfo('UTC')).strftime('%Y-%m-%d %H:%M:%S')

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            calendar = create('resource.calendar', {'name': 'Pencil split schedule',
                'tz': str(timezone), 'attendance_ids': [(5, 0, 0),
                    (0, 0, {'name': 'FN', 'dayofweek': '3', 'day_period': 'morning',
                            'hour_from': 9.75, 'hour_to': 14}),
                    (0, 0, {'name': 'AN', 'dayofweek': '3', 'day_period': 'afternoon',
                            'hour_from': 14.75, 'hour_to': 18.75})]})
            workers = []
            for basis in ('monthly', 'daily', 'hourly'):
                name = 'Pencil Browser ' + basis
                employee = create('hr.employee', {'name': name, 'resource_calendar_id': calendar})
                create('hr.contract', {'name': name + ' contract', 'employee_id': employee,
                    'date_start': '2026-10-01', 'wage_type': basis, 'wage': 8000,
                    'daily_wage': 885, 'hourly_rate': 53, 'resource_calendar_id': calendar})
                punches = []
                for day, start, end in [('2026-10-21', '09:45', '12:00'),
                        ('2026-10-22', '09:45', '14:00'), ('2026-10-22', '14:45', '18:45'),
                        ('2026-10-23', '09:45', '12:00')]:
                    punch = create('hr.attendance', {'employee_id': employee,
                        'check_in': utc(day + ' ' + start), 'check_out': utc(day + ' ' + end)})
                    if day == '2026-10-22':
                        punches.append(punch)
                create('bambus.attendance.day.review', {'date': '2026-10-22', 'company_id': session['user_companies']['current_company'],
                    'employee_id': employee, 'check_in': utc('2026-10-22 09:45'),
                    'check_out': utc('2026-10-22 12:00'), 'worked_hours': 2.25,
                    'fine_state': 'approved', 'fine_hours': 6, 'fine_amount': 187.68})
                workers.append((employee, name, punches))
            page.goto(url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            for employee, name, punches in workers:
                page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                    type: 'ir.actions.client', tag: 'bambus_attendance_editor',
                    params: {selected_date: '2026-10-22'}})""")
                page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill(name)
                card = page.locator('.o_bae_employee').filter(has_text=name)
                expect(card).to_contain_text('8h 15m')
                with page.expect_response(lambda response: response.url.endswith('/hr.attendance/web_search_read')) as loaded:
                    card.get_by_role('button', name='Open attendance entries', exact=True).click()
                page.locator('.o_list_view .o_data_row').first.wait_for()
                assert page.locator('.o_list_view .o_data_row').count() == 2
                rows = page.locator('.o_list_view .o_data_row')
                assert all(name in row.inner_text() for row in rows.all())
                visible = [record['id'] for record in loaded.value.json()['result']['records']]
                assert sorted(visible) == sorted(punches)
                action = rpc('bambus.attendance.dashboard', 'open_dashboard_attendance_entries',
                    [employee, '2026-10-22'])
                assert sorted(rpc('hr.attendance', 'search', [action['domain']])) == sorted(punches)
                # Native ORM edit while away from the dashboard; return through
                # the action stack exactly as the pencil workflow does.
                rpc('hr.attendance', 'write', [[punches[1]],
                    {'check_out': utc('2026-10-22 17:45')}])
                page.evaluate('() => odoo.__WOWL_DEBUG__.root.env.services.action.restore()')
                search = page.get_by_placeholder('Search Staff by Name, Department or Schedule')
                search.fill(name)
                expect(page.locator('.o_bae_employee').filter(has_text=name)).to_contain_text('7h 15m')
                assert page.locator('input[type="date"]').input_value() == '2026-10-22'
                saved = rpc('bambus.attendance.day.review', 'search_read', [[
                    ['date', '=', '2026-10-22'], ['employee_id', '=', employee]]],
                    {'fields': ['fine_hours', 'fine_amount']})[0]
                assert saved['fine_hours'] == 6 and saved['fine_amount'] == 187.68

            # A card without punches must still expose the route and open an empty list.
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type: 'ir.actions.client', tag: 'bambus_attendance_editor',
                params: {selected_date: '2026-10-24'}})""")
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill(workers[0][1])
            with page.expect_response(lambda response: response.url.endswith('/hr.attendance/web_search_read')) as loaded:
                page.locator('.o_bae_employee').filter(has_text=workers[0][1]).get_by_role(
                    'button', name='Open attendance entries', exact=True).click()
            page.locator('.o_list_view').wait_for()
            assert loaded.value.json()['result']['records'] == []
            assert page.locator('.o_list_view .o_data_row').count() == 0
            assert not errors, errors
            print('PASS: installed pencil for Monthly/Daily/Hourly; correct employee/date, split punches, adjacent dates excluded, empty day opens native list; corrected punches refresh on return while approved fines remain saved.')
        finally:
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
