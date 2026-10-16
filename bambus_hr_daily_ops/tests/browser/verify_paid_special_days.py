"""Check paid-off settings and worked-day refresh in an installed Odoo client.

Run on an isolated test DB after upgrading the attendance and payroll modules:
python bambus_hr_daily_ops/tests/browser/verify_paid_special_days.py \
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
            calendar = create('resource.calendar', {'name': 'Paid Off Browser Calendar', 'tz': 'UTC',
                'attendance_ids': [(5, 0, 0), (0, 0, {'name': 'Monday', 'dayofweek': '0',
                    'day_period': 'morning', 'hour_from': 9, 'hour_to': 17})]})
            template = create('bambus.attendance.automation.template', {'name': 'Paid Off Browser Rules',
                'weekly_off_source': 'weekdays', 'weekly_off_sunday': True,
                'weekly_off_overtime_policy': 'all', 'full_day_basis': 'fixed', 'full_day_hours': 9})
            employee = create('hr.employee', {'name': 'Paid Off Browser Employee',
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            contract = create('hr.contract', {'name': 'Paid Off Browser Contract', 'employee_id': employee,
                'date_start': '2026-09-01', 'wage_type': 'monthly', 'wage': 9000,
                'resource_calendar_id': calendar})
            create('resource.calendar.leaves', {'name': 'Paid Off Browser Holiday', 'calendar_id': calendar,
                'date_from': '2026-09-28 00:00:00', 'date_to': '2026-09-28 23:59:59'})

            def open_record(model, record):
                page.goto(url + '/odoo?debug=assets')
                page.wait_for_selector('.o_web_client', timeout=60000)
                page.evaluate("""async ({model, record}) => {
                    await odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                        type: 'ir.actions.act_window', res_model: model, res_id: record,
                        views: [[false, 'form']], target: 'current',
                    });
                }""", {'model': model, 'record': record})
                page.wait_for_selector('.o_form_view')

            open_record('bambus.attendance.automation.template', template)
            page.get_by_role('tab', name='Public Holiday Policy', exact=True).click()
            checkbox = page.locator('.o_field_widget[name="monthly_paid_public_holiday"] input')
            assert not checkbox.is_checked(), 'Existing/default templates must retain disabled holiday credit'
            checkbox.check()
            with page.expect_response(lambda response: '/web_save' in response.url):
                page.locator('.o_form_button_save').click()
            assert rpc('bambus.attendance.automation.template', 'read', [[template]],
                       {'fields': ['monthly_paid_public_holiday']})[0]['monthly_paid_public_holiday']

            for day, field, credit in [('2026-09-27', 'weekend_worked', 'paid_weekly_off_days'),
                                       ('2026-09-28', 'holiday_worked', 'paid_public_holiday_days')]:
                slip = create('hr.payslip', {'name': 'Paid Off Browser ' + day, 'employee_id': employee,
                    'contract_id': contract, 'date_from': day, 'date_to': day})
                rpc('hr.payslip', 'action_compute_sheet', [[slip]])
                initial = rpc('hr.payslip', 'read', [[slip]], {'fields': [credit, 'total_regular_pay_amount']})[0]
                assert initial[credit] == 1 and initial['total_regular_pay_amount'] == 300, initial
                attendance = create('hr.attendance', {'employee_id': employee,
                    'check_in': day + ' 09:00:00', 'check_out': day + ' 17:00:00'})
                for checkout, expected in [('17:00:00', .5), ('18:00:00', 1)]:
                    rpc('hr.attendance', 'write', [[attendance], {'check_out': day + ' ' + checkout}])
                    open_record('hr.payslip', slip)
                    with page.expect_response(lambda response: '/action_compute_sheet' in response.url):
                        page.get_by_role('button', name='Compute Sheet', exact=True).click()
                    record = rpc('hr.payslip', 'read', [[slip]],
                                 {'fields': [field, credit, 'total_regular_pay_amount', 'worked_days_line_ids']})[0]
                    assert record[field] == expected, record
                    assert record[credit] == 1 and record['total_regular_pay_amount'] == 300, record
                    rows = rpc('hr.payslip.worked.days', 'read', [record['worked_days_line_ids']],
                               {'fields': ['code', 'number_of_days']})
                    assert sum(row['number_of_days'] for row in rows) == 1, rows
                    counter = page.locator(f'.o_field_widget[name="{field}"]').first
                    from playwright.sync_api import expect
                    expect(counter).to_have_text(f'{expected:.2f}')
            assert not errors, errors
            print('PASS: installed holiday switch defaults off, enables via UI, and both paid special-day '
                  'payslips retain 300 normal pay while worked days refresh .5 -> 1 and payable days stay 1.')
        finally:
            if 'employee' in locals():
                lines = rpc('bambus.hr.attendance.sheet.line', 'search', [[['employee_id', '=', employee]]])
                if lines:
                    rpc('bambus.hr.attendance.sheet.line', 'unlink', [lines])
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
