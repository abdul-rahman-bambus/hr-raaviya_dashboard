"""Verify draft payroll automation and its existing Excel report in installed Odoo.

Use only an isolated DB containing 'test' in its name. Fixtures are removed.
python hr_payslip_excel_report/tests/browser/verify_draft_payroll.py \
    --url http://localhost:8071 --db raaviya_attendance_test
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
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('Use an isolated test database.')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context = browser.new_context(accept_downloads=True)
        url = args.url.rstrip('/')
        auth = context.request.post(url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert auth.get('result', {}).get('uid'), auth

        def rpc(model, method, values, kwargs=None):
            result = context.request.post(url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {
                    'model': model, 'method': method, 'args': values, 'kwargs': kwargs or {}}}).json()
            assert 'error' not in result, result
            return result['result']

        created = []

        def create(model, values):
            rec = rpc(model, 'create', [values])
            created.append((model, rec))
            return rec

        company = auth['result']['user_companies']['current_company']
        # A dedicated month/company makes the rerun/duplicate assertions independent
        # of other browser fixtures and pre-existing payroll batches.
        test_company = create('res.company', {'name': 'Draft Payroll Browser Company'})
        old_context = rpc('res.users', 'context_get', [])
        allowed = old_context.get('allowed_company_ids', [company])
        # Admin's allowed companies are amended only for this isolated fixture.
        user = auth['result']['uid']
        rpc('res.users', 'write', [[user], {'company_ids': [(4, test_company)]}])
        context_kwargs = {'context': {**old_context, 'allowed_company_ids': [test_company]}}
        original_rpc = rpc

        def rpc(model, method, values, kwargs=None):
            return original_rpc(model, method, values, {**context_kwargs, **(kwargs or {})})

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            calendar = create('resource.calendar', {'name': 'Draft Browser Calendar',
                'company_id': test_company, 'tz': 'UTC', 'attendance_ids': [(5, 0, 0)] + [
                    (0, 0, {'name': 'Work', 'dayofweek': str(day), 'day_period': 'morning',
                            'hour_from': 9, 'hour_to': 17}) for day in range(6)]})
            template = create('bambus.attendance.automation.template', {
                'name': 'Draft Browser Rules', 'company_id': test_company,
                'weekly_off_source': 'weekdays', 'weekly_off_sunday': True,
                'monthly_paid_weekly_off': True, 'monthly_paid_public_holiday': True,
                'overtime_enabled': False, 'late_enabled': False, 'early_exit_enabled': False,
                'full_day_basis': 'fixed', 'full_day_hours': 8, 'half_day_hours': 4})
            employee = create('hr.employee', {'name': 'Draft Browser Employee',
                'company_id': test_company, 'resource_calendar_id': calendar,
                'attendance_automation_template_id': template})
            rule_ids = []
            for name in ['hr_rule_basic', 'hr_rule_taxable', 'hr_rule_net']:
                rule_ids.append(original_rpc('ir.model.data', 'search_read', [[
                    ['module', '=', 'hr_payroll_community'], ['name', '=', name]]], {'fields': ['res_id']})[0]['res_id'])
            structure = create('hr.payroll.structure', {'name': 'Draft Browser Structure',
                'code': 'DRAFT_BROWSER', 'company_id': test_company, 'parent_id': False,
                'rule_ids': [(6, 0, rule_ids)]})
            create('hr.contract', {'name': 'Draft Browser Contract', 'employee_id': employee,
                'company_id': test_company, 'date_start': '2026-10-01', 'wage_type': 'monthly',
                'wage': 12000, 'resource_calendar_id': calendar, 'struct_id': structure, 'state': 'open'})
            wizard = create('payroll.draft.preparation', {'company_id': test_company,
                'month': '2026-10-01', 'employee_ids': [(6, 0, [employee])]})
            context.add_cookies([{'name': 'cids', 'value': str(test_company), 'url': url}])
            page.goto(url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate('''async ({company, wizard}) => {
                await odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                    type: 'ir.actions.act_window', res_model: 'payroll.draft.preparation',
                    res_id: wizard, views: [[false, 'form']], target: 'new',
                });
            }''', {'company': test_company, 'wizard': wizard})
            page.get_by_role('button', name='Generate Missing Drafts', exact=True).click()
            page.get_by_text('Created: 1.', exact=False).wait_for()
            result = rpc('payroll.draft.preparation', 'read', [[wizard], ['batch_id']])[0]
            batch = result['batch_id'][0]
            slips = rpc('hr.payslip', 'search', [[['payslip_run_id', '=', batch]]])
            assert len(slips) == 1, slips
            slip = rpc('hr.payslip', 'read', [slips, ['state', 'line_ids', 'total_regular_pay_amount']])[0]
            assert slip['state'] == 'draft'
            original_lines = slip['line_ids']
            baseline = slip['total_regular_pay_amount']
            page.get_by_role('button', name='Generate Missing Drafts', exact=True).click()
            page.get_by_text('Reused without recomputing: 1.', exact=False).wait_for()
            assert rpc('hr.payslip', 'search', [[['payslip_run_id', '=', batch]]]) == slips
            assert rpc('hr.payslip', 'read', [slips, ['line_ids']])[0]['line_ids'] == original_lines
            create('hr.attendance', {'employee_id': employee, 'check_in': '2026-10-01 09:00:00',
                                     'check_out': '2026-10-01 17:00:00'})
            page.get_by_role('button', name='Recompute Drafts', exact=True).click()
            page.get_by_text('Recomputed: 1 draft payslips.', exact=False).wait_for()
            updated = rpc('hr.payslip', 'read', [slips, ['state', 'total_regular_pay_amount']])[0]
            assert updated['state'] == 'draft'
            assert abs(updated['total_regular_pay_amount'] - baseline - 12000 / 31) < 0.01, updated
            page.get_by_role('button', name='Payroll Report', exact=True).click()
            page.get_by_role('button', name='Download Excel', exact=True).wait_for()
            assert page.locator('.o_field_widget[name="payslip_status"] select').input_value().strip('"') in ['draft', '"draft"']
            with page.expect_download() as downloaded:
                page.get_by_role('button', name='Download Excel', exact=True).click()
            data = open(downloaded.value.path(), 'rb').read()
            with zipfile.ZipFile(io.BytesIO(data)) as workbook:
                strings = workbook.read('xl/sharedStrings.xml').decode()
                assert 'Draft Browser Employee' in strings and 'Draft Payroll - October 2026' in strings
            assert not errors, errors
            print('PASS installed draft payroll: generate, repeat/no duplicates, explicit recompute, Draft report defaults and XLSX download')
        except Exception:
            print('BROWSER CONTENT:', page.locator('body').inner_text()[-4000:])
            raise
        finally:
            if 'batch' in locals():
                slip_ids = rpc('hr.payslip', 'search', [[['payslip_run_id', '=', batch]]])
                if slip_ids:
                    rpc('hr.payslip', 'unlink', [slip_ids])
                rpc('hr.payslip.run', 'unlink', [[batch]])
            # Company rule ownership of shared rules is unchanged by this fixture.
            for model, record in reversed(created):
                if model != 'res.company':
                    rpc(model, 'unlink', [[record]])
            original_rpc('res.users', 'write', [[user], {'company_ids': [(3, test_company)]}])
            original_rpc('res.company', 'unlink', [[test_company]])
            browser.close()


if __name__ == '__main__':
    main()
