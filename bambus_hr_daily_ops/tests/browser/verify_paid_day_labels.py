"""Check template-derived paid-day dashboard labels in an installed Odoo client.

Run on an isolated test DB after upgrading the attendance and payroll modules:
python bambus_hr_daily_ops/tests/browser/verify_paid_day_labels.py \
    --url http://localhost:8071 --db raaviya_attendance_test
Fixtures are removed at the end. Requires Playwright and Chromium.
"""
import argparse
import os

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('Use an isolated test database; this check creates payroll records.')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context = browser.new_context()
        url = args.url.rstrip('/')
        auth = context.request.post(url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert auth.get('result', {}).get('uid'), auth

        def rpc(model, method, values, kwargs=None):
            result = context.request.post(url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {'model': model,
                    'method': method, 'args': values, 'kwargs': kwargs or {}}}).json()
            assert 'error' not in result, result
            return result['result']

        created = []

        def create(model, values):
            rec = rpc(model, 'create', [values])
            created.append((model, rec))
            return rec

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            calendar = create('resource.calendar', {'name': 'Paid Label Calendar', 'tz': 'UTC'})
            template = create('bambus.attendance.automation.template', {
                'name': 'Paid Label Rules', 'weekly_off_source': 'weekdays',
                'weekly_off_sunday': True, 'monthly_paid_weekly_off': True,
                'monthly_paid_public_holiday': True})
            employee = create('hr.employee', {'name': 'Paid Label Browser Employee',
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            create('hr.contract', {'name': 'Paid Label Contract', 'employee_id': employee,
                'date_start': '2026-10-01', 'wage_type': 'monthly', 'wage': 12000,
                'resource_calendar_id': calendar})
            create('resource.calendar.leaves', {'name': 'Paid Label Monday', 'calendar_id': calendar,
                'date_from': '2026-10-19 00:00:00', 'date_to': '2026-10-19 23:59:59'})
            page.goto(url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)

            def check(day, label):
                page.evaluate("""async day => {
                    await odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                        type: 'ir.actions.client', tag: 'bambus_attendance_editor',
                        params: {selected_date: day},
                    });
                }""", day)
                page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Paid Label Browser Employee')
                row = page.locator('.o_bae_employee').filter(has_text='Paid Label Browser Employee')
                row.get_by_text(label, exact=True).wait_for()
                assert label in row.locator('.o_bae_employee_info').inner_text()

            check('2026-10-18', 'Paid Weekly Off')
            check('2026-10-19', 'Paid Public Holiday')
            rpc('bambus.attendance.automation.template', 'write', [[template], {'monthly_paid_public_holiday': False}])
            check('2026-10-19', 'Not Marked')
            assert not errors, errors
            print('PASS installed dashboard: Sunday paid weekly off, Monday paid holiday, switch off restores Not Marked')
        finally:
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
