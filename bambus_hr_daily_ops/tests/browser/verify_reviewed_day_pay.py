"""Check installed review, half-leave confirmation, rates and XLSX on a test DB.

python bambus_hr_daily_ops/tests/browser/verify_reviewed_day_pay.py \
    --url http://localhost:8071 --db YOUR_TEST_DATABASE
Fixtures are removed. Requires Playwright/Chromium, admin/admin test defaults.
"""
import argparse
import io
import os
import zipfile

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--fine-only', action='store_true', help='Verify normal day pay minus approved whole-day missing-time fines.')
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('Use an isolated database containing test in its name.')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'), args=['--no-sandbox'])
        context = browser.new_context(accept_downloads=True)
        response = context.request.post(args.url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert response.get('result', {}).get('uid'), 'Test authentication failed'
        company = response['result']['user_companies']['current_company']

        def rpc(model, method, rpc_args, kwargs=None):
            response = context.request.post(args.url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {'model': model, 'method': method,
                    'args': rpc_args, 'kwargs': kwargs or {}}}).json()
            if 'error' in response:
                raise AssertionError(response['error']['data'].get('message', 'RPC failed'))
            return response['result']

        created, employees = [], []
        def create(model, values):
            record = rpc(model, 'create', [values]); created.append((model, record)); return record
        def ref(module, name):
            return rpc('ir.model.data', 'search_read', [[['module', '=', module], ['name', '=', name]]], {'fields': ['res_id']})[0]['res_id']
        def read(model, record, fields):
            return rpc(model, 'read', [[record]], {'fields': fields})[0]
        def action(page, values):
            page.evaluate('values => odoo.__WOWL_DEBUG__.root.env.services.action.doAction(values)', values)

        try:
            calendar = create('resource.calendar', {'name': 'Reviewed Pay Browser Schedule', 'company_id': company,
                'tz': 'Asia/Kolkata', 'attendance_ids': [(5, 0, 0),
                    (0, 0, {'name': 'FN', 'dayofweek': '0', 'day_period': 'morning', 'hour_from': 9.75, 'hour_to': 14}),
                    (0, 0, {'name': 'AN', 'dayofweek': '0', 'day_period': 'afternoon', 'hour_from': 14.75, 'hour_to': 18.75})]})
            template = create('bambus.attendance.automation.template', {'name': 'Reviewed Pay Browser Policy',
                'company_id': company, 'reviewed_exception_day_pay': 'regularize', 'full_day_basis': 'schedule',
                'partial_attendance_salary_treatment': 'fine_only' if args.fine_only else 'thresholds',
                'late_grace_minutes': 5, 'early_exit_enabled': True, 'fine_calculation_type': 'salary_minute',
                'weekly_off_source': 'weekdays', 'weekly_off_sunday': True})
            rules = []
            for code, category, expression, sequence in [
                ('BASIC', 'BASIC', 'payslip.total_regular_pay_amount', 10),
                ('LF', 'DED', '-payslip.total_fine_amount', 20),
                ('NET', 'NET', 'categories.BASIC + categories.DED', 30)]:
                rules.append(create('hr.salary.rule', {'name': 'Browser ' + code, 'code': code,
                    'category_id': ref('hr_payroll_community', category), 'sequence': sequence,
                    'condition_select': 'none', 'amount_select': 'code', 'amount_python_compute': 'result = ' + expression}))
            structure = create('hr.payroll.structure', {'name': 'Reviewed Pay Browser Payroll', 'code': 'BROWSER_REVIEWED',
                'parent_id': False, 'rule_ids': [(6, 0, rules)]})
            slips, lines = [], []
            actual_hours = 2.25 if args.fine_only else 7.5
            for wage_type in ('monthly', 'daily', 'hourly'):
                employee = create('hr.employee', {'name': 'Reviewed Browser ' + wage_type, 'company_id': company,
                    'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
                employees.append(employee)
                contract = create('hr.contract', {'name': 'Reviewed Browser Contract ' + wage_type,
                    'company_id': company, 'employee_id': employee, 'date_start': '2026-10-01',
                    'wage_type': wage_type, 'wage': 8000, 'daily_wage': 885, 'hourly_rate': 53,
                    'resource_calendar_id': calendar, 'struct_id': structure})
                # Asia/Kolkata 10:00-14:00 and 14:45-18:15, 7.5 actual hours.
                spans = [('04:15:00', '06:30:00')] if args.fine_only else [('04:30:00', '08:30:00'), ('09:15:00', '12:45:00')]
                for check_in, check_out in spans:
                    create('hr.attendance', {'employee_id': employee, 'check_in': '2026-10-26 ' + check_in,
                                             'check_out': '2026-10-26 ' + check_out})
                slip = create('hr.payslip', {'name': 'Reviewed Browser Payslip ' + wage_type, 'employee_id': employee,
                    'contract_id': contract, 'struct_id': structure, 'date_from': '2026-10-26', 'date_to': '2026-10-26'})
                slips.append(slip)
                rpc('hr.payslip', 'action_compute_sheet', [[slip]])
                before = read('hr.payslip', slip, ['total_regular_pay_amount', 'total_working_days'])
                fraction = 1 if args.fine_only else .5
                expected = 8000 / 31 * fraction if wage_type == 'monthly' else 885 * fraction if wage_type == 'daily' else actual_hours * 53
                assert abs(before['total_regular_pay_amount'] - expected) < .01, before
                if wage_type != 'hourly':
                    payload = rpc('bambus.attendance.dashboard', 'get_dashboard_review', [employee, '2026-10-26'])
                    labels = {'Early Exit Fine'} if args.fine_only else {'First Half: Late Entry', 'Second Half: Early Exit'}
                    assert {item['label'] for item in payload['items']} == labels, payload
                    if args.fine_only:
                        assert payload['items'][0]['hours'] == 6, payload
                    line = read('bambus.hr.attendance.review.wizard', payload['wizard_id'], ['line_id'])['line_id'][0]
                    lines.append(line)

            if args.fine_only:
                dashboard = rpc('bambus.attendance.dashboard', 'get_attendance_dashboard', [], {'selected_date': '2026-10-26'})
                for row in dashboard['daily_attendance']:
                    if row['id'] in employees[:2]:
                        assert row['fine_hours'] == 6, {key: row.get(key) for key in ('name', 'fine_hours', 'fine_review_pending', 'fine_enabled')}

            page = context.new_page(); errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            # Installed backend form contains the new policy selector.
            action(page, {'type': 'ir.actions.act_window', 'res_model': 'bambus.attendance.automation.template',
                          'res_id': template, 'views': [[False, 'form']], 'target': 'current'})
            page.get_by_role('tab', name='Late & Early Exit', exact=True).click()
            policy = page.locator('.o_field_widget[name="partial_attendance_salary_treatment"] select')
            assert policy.input_value().strip('"') == ('fine_only' if args.fine_only else 'thresholds')
            selector = page.locator('.o_field_widget[name="reviewed_exception_day_pay"] select')
            if args.fine_only:
                assert not selector.is_visible()
            else:
                assert selector.input_value().strip('"') == 'regularize'
            # Exercise real dashboard review rows, Ignore and approval navigation.
            action(page, {'type': 'ir.actions.client', 'tag': 'bambus_attendance_editor',
                          'params': {'selected_date': '2026-10-26', 'metric_filter': 'fine'}})
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Reviewed Browser')
            for wage_type in ('monthly', 'daily'):
                row = page.locator('.o_bae_employee').filter(has_text='Reviewed Browser ' + wage_type)
                row.get_by_title('Review late / fine', exact=True).click()
                modal = page.locator('.o_baa_modal')
                modal.get_by_text('Early Exit Fine' if args.fine_only else 'First Half: Late Entry', exact=True).wait_for()
                if not args.fine_only:
                    # Ignore morning cab delay; fine-only mode approves all six early-exit hours.
                    modal.get_by_role('button', name='Delete / Ignore').first.click()
                modal.get_by_role('button', name='Approve Remaining Items').click()
                modal.wait_for(state='hidden')
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Reviewed Browser')
            page.locator('.o_bae_employee').filter(has_text='Reviewed Browser hourly').wait_for()
            assert page.locator('input[type=date]').input_value() == '2026-10-26'
            for index, expected in enumerate((8000 / 31, 885, actual_hours * 53)):
                rpc('hr.payslip', 'action_compute_sheet', [[slips[index]]])
                result = read('hr.payslip', slips[index], ['total_regular_pay_amount', 'total_fine_amount', 'total_working_days', 'attendance_deduction_detail_ids'])
                assert abs(result['total_regular_pay_amount'] - expected) < .01, result
                if args.fine_only:
                    totals = read('hr.payslip', slips[index], ['basic_pay', 'net_pay'])
                    assert abs(totals['net_pay'] - (70.38, 241.36, 119.25)[index]) < .01, totals
                if index < 2:
                    assert result['total_working_days'] == 1, result
                    detail = read('bambus.hr.payslip.attendance.detail', result['attendance_deduction_detail_ids'][0], ['rate', 'rate_unit', 'hours', 'amount'])
                    assert detail['rate_unit'] == 'per minute', detail
                    assert abs(detail['rate'] * detail['hours'] * 60 - detail['amount']) < .01, detail
            action(page, {'type': 'ir.actions.act_window', 'res_model': 'hr.payslip', 'res_id': slips[0],
                          'views': [[False, 'form']], 'target': 'current'})
            page.get_by_role('tab', name='Deductions', exact=True).click()
            assert page.get_by_text('per minute', exact=True).is_visible()
            # Export through the real HTTP download, retaining salary snapshots.
            for report_type in ('review', 'summary'):
                wizard = create('payslip.excel.wizard', {'report_type': report_type, 'company_id': company,
                    'duration_type': 'custom', 'start_date': '2026-10-26', 'end_date': '2026-10-26',
                    'employee_ids': [(6, 0, employees)], 'payslip_status': 'draft'})
                download = rpc('payslip.excel.wizard', 'action_download_payslip_excel_report', [[wizard]])
                contents = context.request.get(args.url + download['url']).body()
                with zipfile.ZipFile(io.BytesIO(contents)) as archive:
                    strings = archive.read('xl/sharedStrings.xml').decode()
                    assert 'Reviewed Exception Hours' in strings
                    assert all('Reviewed Browser ' + kind in strings for kind in ('monthly', 'daily', 'hourly'))
            if not args.fine_only:
                # Existing aggregate approval: reassessment is explicit and Cancel preserves it.
                rpc('bambus.attendance.day.review', 'write', [[lines[0]], {
                    'fine_state': 'approved', 'fine_hours': .5, 'fine_amount': 10,
                    'fine_calculation_type': 'fixed', 'fine_rate': 10,
                    'fine_review_data': {'late': {'state': 'approved', 'hours': .5, 'amount': 10,
                                                 'calculation_type': 'fixed', 'rate': 10}}}])
                action(page, {'type': 'ir.actions.client', 'tag': 'bambus_attendance_editor', 'params': {'selected_date': '2026-10-26'}})
                page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Reviewed Browser monthly')
                row = page.locator('.o_bae_employee').filter(has_text='Reviewed Browser monthly')
                row.get_by_title('Review late / fine', exact=True).click()
                modal = page.locator('.o_baa_modal')
                modal.get_by_role('button', name='Review Session Exceptions', exact=True).click()
                modal.get_by_text('First Half: Late Entry', exact=True).wait_for()
                assert 'replaces the previous fine decisions' in modal.inner_text()
                modal.get_by_role('button', name='Cancel', exact=True).click()
                assert read('bambus.attendance.day.review', lines[0], ['fine_amount'])['fine_amount'] == 10
                row.get_by_title('Review late / fine', exact=True).click()
                modal.get_by_role('button', name='Review Session Exceptions', exact=True).click()
                modal.get_by_text('First Half: Late Entry', exact=True).wait_for()
                modal.get_by_role('button', name='Delete / Ignore').first.click()
                modal.get_by_role('button', name='Delete / Ignore').first.click()
                modal.get_by_role('button', name='Approve Remaining Items').click()
                modal.wait_for(state='hidden')
                assert read('bambus.attendance.day.review', lines[0], ['fine_amount'])['fine_amount'] == 0
                audit = rpc('bambus.hr.attendance.time.audit', 'search_read', [[['employee_id', '=', employees[0]]]],
                            {'fields': ['previous_fine_review'], 'order': 'id desc', 'limit': 1})[0]
                assert audit['previous_fine_review']['amount'] == 10

            # New day: only FN exists, so button must suggest PM without creating a leave.
            # Existing employee's calendar has Monday only; use next Monday for inference.
            create('hr.attendance', {'employee_id': employees[0], 'check_in': '2026-11-02 04:15:00', 'check_out': '2026-11-02 08:30:00'})
            action(page, {'type': 'ir.actions.client', 'tag': 'bambus_attendance_editor', 'params': {'selected_date': '2026-11-02'}})
            row = page.locator('.o_bae_employee').filter(has_text='Reviewed Browser monthly')
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill('Reviewed Browser monthly')
            row.get_by_text('Half Day Leave', exact=True).click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_role('button', name='Create Time Off Request', exact=True).wait_for()
            assert dialog.locator('.o_field_widget[name="period"] select').input_value().strip('"') == 'pm'
            assert not rpc('hr.leave', 'search', [[['employee_id', '=', employees[0]]]])
            dialog.get_by_role('button', name='Cancel', exact=True).click()
            # A visible route back is available from any filtered attendance list.
            page.locator('.o_bad_metric').filter(has_text='Late / Fine Hours').click()
            page.get_by_role('button', name='Daily Attendance', exact=True).click()
            assert page.locator('input[type=date]').input_value() == '2026-11-02'
            page.wait_for_function("document.querySelector('.o_bad_filter_control select').value === 'all'")
            assert page.locator('.o_bad_filter_control select').input_value() == 'all'
            assert page.get_by_placeholder('Search Staff by Name, Department or Schedule').input_value() == ''
            assert not errors, errors
            if args.fine_only:
                print('PASS: fine-only template selector, full day pay before approval, six-hour Early Exit Fine, Monthly net 70.38, Daily net 241.36, Hourly net 119.25, approval navigation, saved rate units, both XLSX exports, explicit half-leave suggestion/Cancel and Daily Attendance button.')
            else:
                print('PASS: installed policy, separate session decisions, broad Late/Fine final-approval navigation and Daily Attendance button, Monthly/Daily day pay, unchanged Hourly hours, rate units, both XLSX exports, explicit legacy reassessment/Cancel/audit, PM half-leave suggestion and Cancel.')
        finally:
            if employees:
                daily_lines = rpc('bambus.attendance.day.review', 'search', [[['employee_id', 'in', employees]]])
                if daily_lines:
                    rpc('bambus.attendance.day.review', 'unlink', [daily_lines])
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
