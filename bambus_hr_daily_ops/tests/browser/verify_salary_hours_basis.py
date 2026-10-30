"""Installed template hours-basis form and dashboard review rate check; test DB only."""
import argparse
import os
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
            calendar = create('resource.calendar', {'name': 'Salary Hours Browser Calendar', 'tz': 'UTC',
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {'name': period, 'dayofweek': '3',
                    'day_period': period, 'hour_from': start, 'hour_to': end}) for period, start, end in
                    [('morning', 9.75, 14), ('afternoon', 14.75, 18.75)]]})
            template = create('bambus.attendance.automation.template', {'name': 'Salary Hours Browser Template',
                'late_enabled': True, 'late_grace_minutes': 5, 'break_enabled': False,
                'early_exit_enabled': False, 'fine_calculation_type': 'salary_minute'})
            employee = create('hr.employee', {'name': 'Salary Hours Browser Employee',
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            create('hr.contract', {'name': 'Salary Hours Browser Contract', 'employee_id': employee,
                'date_start': '2026-10-01', 'resource_calendar_id': calendar,
                'wage_type': 'daily', 'daily_wage': 885, 'wage': 0})
            for start, end in [('09:51:00', '14:00:00'), ('14:45:00', '18:45:00')]:
                create('hr.attendance', {'employee_id': employee,
                    'check_in': '2026-10-22 ' + start, 'check_out': '2026-10-22 ' + end})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate('''id => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type: 'ir.actions.act_window', res_model: 'bambus.attendance.automation.template',
                res_id: id, views: [[false, 'form']], target: 'current'})''', template)
            basis = page.locator('.o_field_widget[name="salary_hours_basis"] select')
            expect(basis).to_have_value('"schedule"')
            fixed = page.locator('.o_field_widget[name="salary_calculation_hours"] input')
            expect(fixed).not_to_be_visible()
            basis.select_option(label='Fixed Hours')
            expect(fixed).to_be_visible()
            fixed.fill('8')
            fixed.press('Tab')
            with page.expect_response(lambda response: '/web_save' in response.url and response.request.method == 'POST') as saved:
                page.locator('.o_form_button_save').click()
            assert 'error' not in saved.value.json(), saved.value.json()
            values = rpc('bambus.attendance.automation.template', 'read', [[template]],
                         {'fields': ['salary_hours_basis', 'salary_calculation_hours']})[0]
            assert values['salary_hours_basis'] == 'fixed' and values['salary_calculation_hours'] == 8, values
            payload = rpc('bambus.attendance.dashboard', 'get_dashboard_review', [employee, '2026-10-22'])
            created.append(('bambus.hr.attendance.review.wizard', payload['wizard_id']))
            assert abs(payload['salary_per_minute'] - 885 / 480) < 1e-6, payload
            assert abs(payload['hourly_rate'] - 885 / 8) < 1e-6, payload
            assert abs(sum(item['hours'] for item in payload['items']) - 1 / 60) < 1e-5, payload
            assert not errors, errors
            print('PASS: schedule default, conditional fixed-hours field, save 8 hours; installed review uses 1.84375/min and 110.625/hour for daily wage 885.')
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
