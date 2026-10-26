"""Exercise extra local HR modules and Apps descriptions without SaaS changes.

python custom_hr_payroll/tests/browser/verify_additional_runtime_warnings.py \
    --url http://localhost:8071 --db YOUR_TEST_DATABASE
Requires Employee Info, Loans, Salary Advance, Playwright and Chromium on a test DB.
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

        created = []
        def create(model, values):
            result = rpc(model, 'create', [values])
            ids = result if isinstance(result, list) else [result]
            created.extend((model, record) for record in ids)
            return result

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            workers = create('hr.employee', [{'name': 'Extra Warning Browser one'}, {'name': 'Extra Warning Browser two'}])
            family = create('hr.employee.family', {'employee_id': workers[0], 'member_name': 'Fixture family',
                'birth_date': '2000-01-01'})
            assert rpc('hr.employee.family', 'read', [[family], ['birth_date']])[0]['birth_date'] == '2000-01-01'
            loans = create('hr.loan', [{'employee_id': worker, 'loan_amount': amount}
                for worker, amount in zip(workers, (1000, 2000))])
            advances = create('salary.advance', [{'employee_id': worker, 'advance': amount}
                for worker, amount in zip(workers, (100, 200))])
            assert len(set(row['name'] for row in rpc('hr.loan', 'read', [loans, ['name']]))) == 2
            assert len(set(row['name'] for row in rpc('salary.advance', 'read', [advances, ['name']]))) == 2
            rpc('salary.advance', 'write', [[advances[0]], {'state': 'submit'}])
            assert rpc('salary.advance', 'read', [[advances[0]], ['state']])[0]['state'] == 'submit'
            page.goto(url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            for model, record in [('hr.employee', workers[0]), ('hr.loan', loans[0]), ('salary.advance', advances[0])]:
                page.evaluate("""value => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                    type: 'ir.actions.act_window', res_model: value.model, res_id: value.id,
                    views: [[false, 'form']], target: 'current'})""", {'model': model, 'id': record})
                page.locator('.o_form_view').wait_for()
            names = ['custom_hr_payroll', 'bambus_hr_daily_ops', 'hr_payslip_excel_report']
            modules = rpc('ir.module.module', 'search_read', [[['name', 'in', names]]],
                {'fields': ['name', 'description_html']})
            assert len(modules) == 3
            for module in modules:
                assert module['description_html'] and 'system-message' not in module['description_html']
            assert not errors, errors
            print('PASS: family values, loan/advance batch sequences, advance status, three installed forms and three Apps descriptions.')
        finally:
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
