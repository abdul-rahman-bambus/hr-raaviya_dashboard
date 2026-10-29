"""Installed correction -> audit -> zero reapproval -> saved payroll -> XLSX.

Use --url http://localhost:8080 --db <isolated_test_database>.
Creates and removes test fixtures. Test credentials use ODOO_TEST_LOGIN/PASSWORD.
"""
import argparse
import io
import os
import re
import zipfile
from uuid import uuid4
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('An isolated database containing test in its name is required.')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'), args=['--no-sandbox'])
        context = browser.new_context()
        auth = context.request.post(args.url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert auth.get('result', {}).get('uid'), 'Test authentication failed'
        company = auth['result']['user_companies']['current_company']
        created = []

        def raw(model, method, values, kwargs=None):
            return context.request.post(args.url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {
                    'model': model, 'method': method, 'args': values, 'kwargs': kwargs or {}}}).json()

        def rpc(model, method, values, kwargs=None):
            result = raw(model, method, values, kwargs)
            assert 'error' not in result, result.get('error', {}).get('data', {}).get('message')
            return result['result']

        def create(model, values):
            record = rpc(model, 'create', [values])
            created.append((model, record))
            return record

        def read(model, record, names):
            return rpc(model, 'read', [[record]], {'fields': names})[0]

        def ref(name):
            return rpc('ir.model.data', 'search_read', [[['module', '=', 'hr_payroll_community'],
                ['name', '=', name]]], {'fields': ['res_id']})[0]['res_id']

        try:
            calendar = create('resource.calendar', {'name': 'Correction Browser Calendar', 'company_id': company,
                'tz': 'UTC', 'attendance_ids': [(5, 0, 0), (0, 0, {'name': 'Thursday',
                    'dayofweek': '3', 'day_period': 'morning', 'hour_from': 9, 'hour_to': 17})]})
            template = create('bambus.attendance.automation.template', {'name': 'Correction Browser Policy',
                'company_id': company, 'late_enabled': True, 'late_grace_minutes': 0,
                'break_enabled': False, 'early_exit_enabled': False, 'full_day_basis': 'schedule',
                'overtime_enabled': True, 'overtime_rate_policy': 'fixed', 'overtime_rate': 120,
                'overtime_calculation_type': 'fixed_hour', 'monthly_paid_weekly_off': False,
                'monthly_paid_public_holiday': False})
            rules = []
            for code, category, expression, sequence in [
                ('BASIC', 'BASIC', 'payslip.total_regular_pay_amount', 10),
                ('OT', 'ALW', 'payslip.total_overtime_amount', 20),
                ('LF', 'DED', '-payslip.total_fine_amount', 30),
                ('GROSS', 'GROSS', 'categories.BASIC + categories.ALW', 40),
                ('NET', 'NET', 'categories.BASIC + categories.ALW + categories.DED', 50)]:
                rules.append(create('hr.salary.rule', {'name': 'Correction Browser ' + code, 'code': code,
                    'category_id': ref(category), 'sequence': sequence, 'condition_select': 'none',
                    'amount_select': 'code', 'amount_python_compute': 'result = ' + expression}))
            structure = create('hr.payroll.structure', {'name': 'Correction Browser Payroll', 'code': 'CORRECTION_BROWSER',
                'parent_id': False, 'rule_ids': [(6, 0, rules)]})
            employee_name = 'Correction Browser Employee ' + uuid4().hex[:8]
            employee = create('hr.employee', {'name': employee_name, 'company_id': company,
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            contract = create('hr.contract', {'name': 'Correction Browser Contract', 'employee_id': employee,
                'company_id': company, 'date_start': '2026-10-01', 'wage_type': 'monthly', 'wage': 16000,
                'resource_calendar_id': calendar, 'struct_id': structure})
            punch = create('hr.attendance', {'employee_id': employee,
                'check_in': '2026-10-29 09:15:00', 'check_out': '2026-10-29 18:00:00'})
            proposal = rpc('bambus.attendance.dashboard', 'get_dashboard_review', [employee, '2026-10-29'])
            wizard = read('bambus.hr.attendance.review.wizard', proposal['wizard_id'], ['line_id', 'fine_line_ids'])
            review = wizard['line_id'][0]
            created.append(('bambus.attendance.day.review', review))
            rpc('bambus.hr.attendance.review.fine', 'write', [wizard['fine_line_ids'], {'calculation_type': 'fixed', 'rate': 100}])
            rpc('bambus.hr.attendance.review.wizard', 'write', [[proposal['wizard_id']], {'calculation_type': 'fixed_hour', 'rate': 120}])
            rpc('bambus.hr.attendance.review.wizard', 'action_save', [[proposal['wizard_id']]])
            slip = create('hr.payslip', {'name': 'Correction Browser Payslip', 'employee_id': employee,
                'contract_id': contract, 'struct_id': structure, 'date_from': '2026-10-29', 'date_to': '2026-10-29'})
            rpc('hr.payslip', 'action_compute_sheet', [[slip]])
            before = read('hr.payslip', slip, ['net_pay', 'total_fine_amount', 'total_overtime_amount'])
            assert before['total_fine_amount'] == 100 and before['total_overtime_amount'] == 120, before
            rpc('hr.attendance', 'write', [[punch], {'check_in': '2026-10-29 09:00:00'}],
                {'context': {'attendance_change_reason': 'Corrected mistyped arrival'}})
            flags = read('bambus.attendance.day.review', review, ['fine_re_review_required', 'overtime_state', 'overtime_amount'])
            assert flags['fine_re_review_required'] and flags['overtime_state'] == 'approved' and flags['overtime_amount'] == 120
            blocked = raw('hr.payslip', 'action_compute_sheet', [[slip]])
            assert 'Review corrected attendance' in blocked['error']['data']['message']
            page = context.new_page()
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({type:'ir.actions.client',
                tag:'bambus_attendance_editor', params:{selected_date:'2026-10-29', metric_filter:'fine'}})""")
            page.get_by_placeholder('Search Staff by Name, Department or Schedule').fill(employee_name)
            card = page.locator('.o_bae_employee').filter(has_text=employee_name)
            expect(card).to_be_visible()
            card.get_by_role('button', name=re.compile('Logs')).click()
            logs = page.locator('.o_bea_log_modal')
            expect(logs).to_contain_text('requires re-review')
            expect(logs).to_contain_text('100.00')
            expect(logs).to_contain_text('Corrected mistyped arrival')
            logs.get_by_role('button', name='Close', exact=True).click()
            card.locator('.o_bae_action.fine').click()
            modal = page.locator('.o_baa_modal')
            expect(modal).to_contain_text('Attendance was corrected')
            expect(modal.get_by_text('System calculated: 00:00')).to_be_visible()
            modal.get_by_role('button', name='Approve Remaining Items').click()
            expect(modal).not_to_be_visible()
            assert not read('bambus.attendance.day.review', review, ['fine_re_review_required'])['fine_re_review_required']
            rpc('hr.payslip', 'action_compute_sheet', [[slip]])
            after = read('hr.payslip', slip, ['net_pay', 'total_fine_amount', 'total_overtime_amount'])
            assert after['total_fine_amount'] == 0 and after['total_overtime_amount'] == 120, after
            assert abs(after['net_pay'] - before['net_pay'] - 100) < .01
            export = create('payslip.excel.wizard', {'report_type': 'summary', 'company_id': company,
                'duration_type': 'custom', 'start_date': '2026-10-29', 'end_date': '2026-10-29',
                'payslip_status': 'draft', 'employee_ids': [(6, 0, [employee])]})
            action = rpc('payslip.excel.wizard', 'action_download_payslip_excel_report', [[export]])
            response = context.request.get(args.url + action['url'])
            assert response.ok
            with zipfile.ZipFile(io.BytesIO(response.body())) as archive:
                ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                net = sheet.find("s:sheetData/s:row/s:c[@r='W7']/s:v", ns)
                assert abs(float(net.text) - after['net_pay']) < .01
            print('PASS: corrected punch -> old approval audited -> zero fine pending -> payroll blocked -> visible Logs and warning -> UI reapproval -> unchanged OT -> recomputed salary and XLSX reconcile.')
        finally:
            for model, record in reversed(created):
                rpc(model, 'unlink', [[record]])
            browser.close()


if __name__ == '__main__':
    main()
