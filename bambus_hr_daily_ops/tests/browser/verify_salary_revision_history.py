"""Installed salary revision history and employee overview layout; test DB only."""
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

        def ref(module, name):
            return rpc('ir.model.data', 'search_read', [[['module', '=', module], ['name', '=', name]]],
                       {'fields': ['res_id']})[0]['res_id']

        try:
            rules = []
            for code, expression in [('BASIC', 'contract.daily_wage'), ('GROSS', 'categories.BASIC'), ('NET', 'categories.BASIC')]:
                rules.append(create('hr.salary.rule', {'name': 'History browser ' + code, 'code': code,
                    'sequence': len(rules) * 10 + 10, 'category_id': ref('hr_payroll_community', code),
                    'condition_select': 'none', 'amount_select': 'code', 'amount_python_compute': 'result = ' + expression}))
            structure = create('hr.payroll.structure', {'name': 'History browser structure', 'code': 'HISTORY_BROWSER',
                'parent_id': False, 'rule_ids': [(6, 0, rules)]})
            employee = create('hr.employee', {'name': 'Salary History Browser Employee'})
            contract = create('hr.contract', {'name': 'Salary History Browser Contract', 'employee_id': employee,
                'date_start': '2026-10-01', 'wage_type': 'daily', 'daily_wage': 885, 'wage': 0,
                'struct_id': structure})
            slip = create('hr.payslip', {'name': 'Salary Slip for History Browser October 2026',
                'employee_id': employee, 'contract_id': contract, 'struct_id': structure,
                'date_from': '2026-10-01', 'date_to': '2026-10-31'})
            wizard = create('hr.salary.revision.wizard', {'payslip_id': slip, 'revised_wage': 900,
                'reason': 'History browser revision', 'revised_wage_type': 'daily',
                'revised_calendar_id': rpc('hr.contract', 'read', [[contract], ['resource_calendar_id']])[0]['resource_calendar_id'][0],
                'effective_date': '2026-10-01'})
            rpc('hr.salary.revision.wizard', 'action_apply_revision', [[wizard]])
            page = context.new_page()
            page.set_viewport_size({'width': 1920, 'height': 1080})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""id => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type:'ir.actions.act_window', res_model:'hr.payslip', res_id:id,
                views:[[false,'form']], target:'current'})""", slip)
            page.locator('button[name=action_open_salary_revision_history]').click()
            history = page.locator('.o_list_table .o_data_row')
            expect(history).to_have_count(1)
            expect(history).to_contain_text('885.00')
            expect(history).to_contain_text('900.00')
            history.click()
            expect(page.get_by_text('Before Revision', exact=True)).to_be_visible()
            expect(page.get_by_text('After Revision', exact=True)).to_be_visible()
            expect(page.locator('.o_field_widget[name=previous_wage]')).to_contain_text('885.00')
            expect(page.locator('.o_field_widget[name=revised_wage]')).to_contain_text('900.00')
            page.screenshot(path='work/salary-revision-history.png', full_page=True)
            page.evaluate("""id => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type:'ir.actions.act_window', res_model:'hr.employee', res_id:id,
                views:[[false,'form']], target:'current'})""", employee)
            page.get_by_role('tab', name='Salary Overview', exact=True).click()
            overview = page.locator('.o_bambus_salary_overview')
            expect(overview.locator('button[name=action_open_salary_revision_history]')).to_be_visible()
            expect(overview).to_contain_text('Latest Confirmed Net')
            expect(overview).to_contain_text('confirmed payslips only')
            row = overview.locator('.o_data_row')
            expect(row).to_have_count(1)
            expect(row).to_contain_text('900.00')
            row.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            assert overview.locator('thead').evaluate('(el) => getComputedStyle(el).position') == 'static'
            bounds = overview.locator('thead').bounding_box()
            row_bounds = row.bounding_box()
            assert row_bounds['y'] >= bounds['y'] + bounds['height'] - 1, (bounds, row_bounds)
            assert row_bounds['height'] >= 36, row_bounds
            container = overview.locator('.o_bso_list').bounding_box()
            assert bounds['y'] >= container['y'], (bounds, container)
            assert bounds['x'] >= container['x'], (bounds, container)
            page.screenshot(path='work/salary-overview-layout.png', full_page=True)
            overview.locator('button[name=action_open_salary_revision_history]').click()
            expect(page.locator('.o_list_table .o_data_row')).to_have_count(1)
            assert not errors, errors
            print('PASS: employee/payslip revision history opens saved 885 to 900 detail; draft overview labels explicit and table rows do not overlap headers.')
        except Exception:
            if 'page' in locals():
                page.screenshot(path='work/salary-history-failure.png', full_page=True)
                print('Browser errors:', errors)
                print(page.locator('body').inner_text()[-4000:])
            raise
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
