"""Exercise Odoo 18 payroll kanban cards and precise salary computation.

python custom_hr_payroll/tests/browser/verify_payroll_runtime_views.py \
    --url http://localhost:8071 --db YOUR_TEST_DATABASE
Requires Playwright/Chromium. Self-created fixtures are removed.
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
            record = rpc(model, 'create', [values])
            created.append((model, record))
            return record

        def ref(name):
            return rpc('ir.model.data', 'search_read', [[['module', '=', 'hr_payroll_community'],
                ['name', '=', name]]], {'fields': ['res_id']})[0]['res_id']

        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            rule = create('hr.salary.rule', {'name': 'Runtime Warning Rule', 'code': 'BASIC',
                'category_id': ref('BASIC'), 'condition_select': 'none', 'amount_select': 'fix',
                'amount_fix': 1234.56, 'sequence': 10})
            net = create('hr.salary.rule', {'name': 'Runtime Warning Net', 'code': 'NET', 'sequence': 20,
                'category_id': ref('NET'), 'condition_select': 'none', 'amount_select': 'code',
                'amount_python_compute': 'result = categories.BASIC'})
            structure = create('hr.payroll.structure', {'name': 'Runtime Warning Structure', 'code': 'WARN_RUNTIME',
                'parent_id': False, 'rule_ids': [(6, 0, [rule, net])]})
            employee = create('hr.employee', {'name': 'Runtime Warning Employee'})
            contract = create('hr.contract', {'name': 'Runtime Warning Contract', 'employee_id': employee,
                'date_start': '2026-10-01', 'wage_type': 'monthly', 'wage': 8000, 'struct_id': structure})
            batch = create('hr.payslip.run', {'name': 'Runtime Warning Batch',
                'date_start': '2026-10-01', 'date_end': '2026-10-31'})
            slip = create('hr.payslip', {'name': 'Runtime Warning Payslip', 'employee_id': employee,
                'contract_id': contract, 'struct_id': structure, 'payslip_run_id': batch,
                'date_from': '2026-10-01', 'date_to': '2026-10-31'})
            rpc('hr.payslip', 'action_compute_sheet', [[slip]])
            result = rpc('hr.payslip', 'read', [[slip], ['basic_pay', 'net_pay', 'state']])[0]
            assert result == {'id': slip, 'basic_pay': 1234.56, 'net_pay': 1234.56, 'state': 'draft'}, result
            page.goto(url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            for model, record, name, view in [
                ('hr.salary.rule', rule, 'Runtime Warning Rule', 'hr_salary_rule_view_kanban'),
                ('hr.payroll.structure', structure, 'Runtime Warning Structure', 'hr_payroll_structure_view_kanban'),
                ('hr.payslip', slip, 'Runtime Warning Payslip', 'hr_payslip_view_kanban'),
                ('hr.payslip.run', batch, 'Runtime Warning Batch', 'hr_payslip_run_view_kanban')]:
                page.evaluate("""values => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                    type: 'ir.actions.act_window', res_model: values.model, target: 'current',
                    views: [[values.view, 'kanban'], [false, 'form']], domain: [['id', '=', values.id]]})""",
                    {'model': model, 'id': record, 'view': ref(view)})
                card = page.locator('.o_kanban_record').filter(has_text=name)
                card.wait_for()
                card.click()
                page.locator('.o_form_view').wait_for()
            assert not errors, errors
            print('PASS: salary rule, structure, payslip and batch Odoo 18 cards open forms; exact 1234.56 computation, Draft retained.')
        finally:
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
