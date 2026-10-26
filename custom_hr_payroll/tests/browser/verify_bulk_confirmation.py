"""Verify the installed list Actions > Confirm Payslips workflow on a test DB.

python custom_hr_payroll/tests/browser/verify_bulk_confirmation.py \
    --url http://localhost:8071 --db YOUR_TEST_DATABASE
Requires Playwright/Chromium. Only self-created fixtures are confirmed/removed.
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
        parser.error('Use an isolated database containing test in its name.')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'),
            args=['--no-sandbox'])
        context = browser.new_context()
        url = args.url.rstrip('/')
        auth = context.request.post(url + '/web/session/authenticate', data={'jsonrpc': '2.0', 'method': 'call',
            'params': {'db': args.db, 'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert auth.get('result', {}).get('uid'), 'Test authentication failed'

        def rpc(model, method, values, kwargs=None):
            result = context.request.post(url + '/web/dataset/call_kw', data={'jsonrpc': '2.0', 'method': 'call',
                'params': {'model': model, 'method': method, 'args': values, 'kwargs': kwargs or {}}}).json()
            assert 'error' not in result, result.get('error', {}).get('data', {}).get('message')
            return result['result']

        created, slips = [], []
        def create(model, values):
            record = rpc(model, 'create', [values])
            created.append((model, record))
            return record

        def ref(module, name):
            return rpc('ir.model.data', 'search_read', [[['module', '=', module], ['name', '=', name]]],
                {'fields': ['res_id']})[0]['res_id']

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            basic = create('hr.salary.rule', {'name': 'Bulk browser basic', 'code': 'BASIC', 'sequence': 10,
                'category_id': ref('hr_payroll_community', 'BASIC'), 'condition_select': 'none',
                'amount_select': 'fix', 'amount_fix': 1000})
            net = create('hr.salary.rule', {'name': 'Bulk browser net', 'code': 'NET', 'sequence': 20,
                'category_id': ref('hr_payroll_community', 'NET'), 'condition_select': 'none',
                'amount_select': 'code', 'amount_python_compute': 'result = categories.BASIC'})
            structure = create('hr.payroll.structure', {'name': 'Bulk browser structure', 'code': 'BULK_BROWSER',
                'parent_id': False, 'rule_ids': [(6, 0, [basic, net])]})
            workers = []
            for basis in ('monthly', 'daily', 'hourly'):
                employee = create('hr.employee', {'name': 'Bulk Browser ' + basis})
                workers.append(employee)
                contract = create('hr.contract', {'name': 'Bulk browser ' + basis, 'employee_id': employee,
                    'date_start': '2026-10-01', 'wage_type': basis, 'wage': 8000, 'daily_wage': 885,
                    'hourly_rate': 53, 'struct_id': structure})
                slips.append(create('hr.payslip', {'employee_id': employee, 'contract_id': contract,
                    'struct_id': structure, 'date_from': '2026-10-01', 'date_to': '2026-10-31'}))
            rpc('hr.payslip', 'action_compute_sheet', [slips])
            page.goto(url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""ids => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type: 'ir.actions.act_window', res_model: 'hr.payslip', name: 'Bulk confirmation test',
                views: [[false, 'list'], [false, 'form']], domain: [['id', 'in', ids]], target: 'current'})""", slips)
            page.locator('.o_list_table .o_data_row').first.wait_for()
            assert page.locator('.o_list_table .o_data_row').count() == 3
            page.locator('.o_list_table thead input[type=checkbox]').check()
            def open_wizard():
                if not page.locator('.o_list_table thead input[type=checkbox]').is_checked():
                    page.locator('.o_list_table thead input[type=checkbox]').check()
                page.locator('.o_cp_action_menus button').filter(has_text='Actions').click()
                page.get_by_role('menuitem', name='Confirm Payslips', exact=True).click()
                dialog = page.get_by_role('dialog')
                dialog.get_by_role('button', name='Confirm Selected Payslips', exact=True).wait_for()
                assert dialog.locator('.o_data_row').count() == 3
                return dialog
            dialog = open_wizard()
            dialog.get_by_role('button', name='Cancel', exact=True).click()
            assert all(row['state'] == 'draft' for row in rpc('hr.payslip', 'read', [slips, ['state']]))
            dialog = open_wizard()
            dialog.get_by_role('button', name='Confirm Selected Payslips', exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            totals = rpc('hr.payslip', 'read', [slips, ['state', 'net_pay', 'paid']])
            assert all(row['state'] == 'done' and row['net_pay'] == 1000 and not row['paid'] for row in totals), totals
            # Done reporting reads the same saved amounts; Draft excludes them.
            wizard = create('payslip.excel.wizard', {'duration_type': 'custom', 'start_date': '2026-10-01',
                'end_date': '2026-10-31', 'employee_ids': [(6, 0, workers)]})
            assert rpc('payslip.excel.wizard', 'read', [[wizard], ['payslip_status']])[0]['payslip_status'] == 'draft'
            rpc('payslip.excel.wizard', 'write', [[wizard], {'payslip_status': 'done'}])
            download = rpc('payslip.excel.wizard', 'action_download_payslip_excel_report', [[wizard]])
            response = context.request.get(url + download['url'])
            assert response.ok and response.body().startswith(b'PK')
            assert not errors, errors
            print('PASS: native list action, three wage types, Cancel, bulk Done with net 3000 unchanged, no payment flag, Done XLSX download.')
        except Exception:
            page.screenshot(path='work/bulk-confirm-browser-failure.png', full_page=True)
            print('Visible buttons:', page.get_by_role('button').all_text_contents())
            raise
        finally:
            # Native payroll does not allow unlinking Done records; reset only
            # these isolated browser fixtures before removing them.
            if slips:
                rpc('hr.payslip', 'write', [slips, {'state': 'draft'}])
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
