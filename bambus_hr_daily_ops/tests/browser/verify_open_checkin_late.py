"""Installed open-punch late arrival on list, dashboard and review; test DB only."""
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
            calendar = create('resource.calendar', {'name': 'Open Late Browser Calendar', 'tz': 'UTC',
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {'name': period, 'dayofweek': '3',
                    'day_period': period, 'hour_from': start, 'hour_to': end})
                    for period, start, end in [('morning', 9.75, 14), ('afternoon', 14.75, 18.75)]]})
            template = create('bambus.attendance.automation.template', {'name': 'Open Late Browser Template',
                'partial_attendance_salary_treatment': 'fine_only', 'late_enabled': True,
                'late_grace_minutes': 5, 'early_exit_enabled': True, 'break_enabled': True,
                'fine_calculation_type': 'salary_minute'})
            employee = create('hr.employee', {'name': 'Open Late Browser Employee',
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            create('hr.contract', {'name': 'Open Late Browser Contract', 'employee_id': employee,
                'date_start': '2026-10-01', 'resource_calendar_id': calendar,
                'wage_type': 'daily', 'daily_wage': 885, 'wage': 0})
            punch = create('hr.attendance', {'employee_id': employee, 'check_in': '2026-10-22 09:57:00'})
            row = next(row for row in rpc('bambus.attendance.dashboard', 'get_attendance_dashboard',
                       ['2026-10-22'])['daily_attendance'] if row['id'] == employee)
            assert row['fine_hours'] == .12 and row['fine_review_pending'], row
            values = rpc('hr.attendance', 'read', [[punch], ['bambus_fine_hours', 'bambus_fine_amount',
                         'worked_hours', 'bambus_early_leave_minutes', 'bambus_gap_minutes']])[0]
            assert abs(values['bambus_fine_hours'] - 7 / 60) < .000001, values
            assert values['worked_hours'] == values['bambus_early_leave_minutes'] == values['bambus_gap_minutes'] == 0
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({type:'ir.actions.client',
                tag:'bambus_attendance_editor', params:{selected_date:'2026-10-22'}})""")
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Open Late Browser Employee')
            card = page.locator('.o_bae_employee').filter(has_text='Open Late Browser Employee')
            expect(card).to_be_visible()
            expect(card).to_contain_text('0h 07m')
            card.get_by_role('button', name=re.compile('Late.*Fine')).click()
            modal = page.get_by_role('dialog')
            expect(modal).to_contain_text('Late Fine')
            expect(modal).to_contain_text('System calculated: 00:07')
            expect(modal).not_to_contain_text('Early Exit Fine')
            modal.get_by_role('button', name='Cancel', exact=True).click()
            assert not errors, errors
            print('PASS: open check-in shows seven post-grace late minutes on dashboard, stored attendance and review; no forecast early/gap/worked hours.')
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
