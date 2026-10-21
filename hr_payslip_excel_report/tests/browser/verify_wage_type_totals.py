"""Verify installed payslip headers for three wage-specific BASIC codes.

Use an isolated test DB. Login defaults to admin/admin, override through
ODOO_TEST_LOGIN and ODOO_TEST_PASSWORD. Fixtures are removed after the check.
"""
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
        parser.error('An isolated test database is required')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'),
                                    args=['--no-sandbox'])
        context = browser.new_context()
        response = context.request.post(args.url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert response.get('result', {}).get('uid'), 'Authentication failed'
        company = response['result']['user_companies']['current_company']

        def rpc(model, method, values, kwargs=None):
            result = context.request.post(args.url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {
                    'model': model, 'method': method, 'args': values, 'kwargs': kwargs or {}}}).json()
            assert 'error' not in result, result.get('error', {}).get('data', {}).get('message')
            return result['result']

        categories = {row['code']: row['id'] for row in rpc('hr.salary.rule.category', 'search_read',
            [[['code', 'in', ['BASIC', 'GROSS', 'NET']]]], {'fields': ['code']})}
        cleanup = {'hr.employee': [], 'hr.contract': [], 'hr.payslip': [], 'hr.salary.rule': []}
        page = context.new_page()
        try:
            for basis, amount in [('monthly', 1000), ('daily', 500), ('hourly', 100)]:
                employee = rpc('hr.employee', 'create', [{'name': 'Header Browser ' + basis, 'company_id': company}])
                cleanup['hr.employee'].append(employee)
                contract = rpc('hr.contract', 'create', [{'name': 'Header browser contract',
                    'employee_id': employee, 'company_id': company, 'date_start': '2026-10-20',
                    'wage_type': basis, 'wage': 31000, 'daily_wage': 1000, 'hourly_rate': 100}])
                cleanup['hr.contract'].append(contract)
                slip = rpc('hr.payslip', 'create', [{'employee_id': employee, 'contract_id': contract,
                    'company_id': company, 'date_from': '2026-10-20', 'date_to': '2026-10-26'}])
                cleanup['hr.payslip'].append(slip)
                for code, category in [('BASIC_' + basis.upper(), 'BASIC'), ('GROSS', 'GROSS'), ('NET', 'NET')]:
                    rule = rpc('hr.salary.rule', 'create', [{'name': 'Header browser ' + code,
                        'code': code, 'category_id': categories[category]}])
                    cleanup['hr.salary.rule'].append(rule)
                    rpc('hr.payslip.line', 'create', [{'name': code, 'code': code,
                        'salary_rule_id': rule, 'category_id': categories[category],
                        'slip_id': slip, 'employee_id': employee, 'contract_id': contract,
                        'amount': amount, 'quantity': 2, 'rate': 100}])
                totals = rpc('hr.payslip', 'read', [[slip], ['basic_pay', 'gross_pay', 'net_pay']])[0]
                assert all(totals[key] == amount * 2 for key in ['basic_pay', 'gross_pay', 'net_pay'])
                page.goto(args.url + '/odoo?debug=assets')
                page.wait_for_selector('.o_web_client', timeout=60000)
                page.evaluate("""async id => {
                    await odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                        type: 'ir.actions.act_window', res_model: 'hr.payslip', res_id: id,
                        views: [[false, 'form']], target: 'current',
                    });
                }""", slip)
                for field in ['basic_pay', 'gross_pay', 'net_pay']:
                    expect(page.locator('.o_field_widget[name="' + field + '"]')).to_contain_text(
                        re.compile(re.escape(f'{amount * 2:,.2f}')))
            print('PASS: installed Monthly/Daily/Hourly headers use wage-specific BASIC categories and saved totals')
        finally:
            for model in ['hr.payslip', 'hr.contract', 'hr.employee', 'hr.salary.rule']:
                if cleanup[model]:
                    rpc(model, 'unlink', [cleanup[model]])
            browser.close()


if __name__ == '__main__':
    main()
