"""Exercise the installed report wizard and real XLSX download in an isolated test DB.

Run: python hr_payslip_excel_report/tests/browser/verify_report_wizard.py \
    --url http://localhost:8071 --db YOUR_TEST_DATABASE --output /tmp/payroll-review.xlsx
Requires Playwright and Chromium; test login/password default to admin/admin.
"""
import argparse
import io
import os
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if 'test' not in args.db.lower():
        parser.error('Use an isolated test database; this check creates and removes a test employee.')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium'),
                                              args=['--no-sandbox'])
        context = browser.new_context(accept_downloads=True)
        response = context.request.post(args.url + '/web/session/authenticate', data={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'db': args.db,
                'login': os.environ.get('ODOO_TEST_LOGIN', 'admin'),
                'password': os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert response.get('result', {}).get('uid'), 'Test authentication failed'
        company = response['result']['user_companies']['current_company']

        def rpc(model, method, rpc_args, kwargs=None):
            result = context.request.post(args.url + '/web/dataset/call_kw', data={
                'jsonrpc': '2.0', 'method': 'call', 'params': {
                    'model': model, 'method': method, 'args': rpc_args, 'kwargs': kwargs or {}}}).json()
            if 'error' in result:
                raise AssertionError(result['error']['data'].get('message', 'RPC failed'))
            return result['result']

        employee = rpc('hr.employee', 'create', [{'name': 'Payroll Browser Verification', 'company_id': company}])
        payslips = []
        contract = False
        batch = False
        empty_wizard = False
        try:
            contract = rpc('hr.contract', 'create', [{'name': 'Browser Monthly Contract',
                'employee_id': employee, 'company_id': company, 'date_start': '2026-09-01',
                'wage_type': 'monthly', 'wage': 9000}])
            for index in range(2):
                payslips.append(rpc('hr.payslip', 'create', [{'name': f'Browser Duplicate {index}',
                    'employee_id': employee, 'company_id': company, 'contract_id': contract,
                    'date_from': '2026-09-01', 'date_to': '2026-09-30'}]))
            shortcut = rpc('ir.model.data', 'search_read', [[['module', '=', 'hr_payslip_excel_report'],
                ['name', '=', 'menu_hrms_payroll_reports']]], {'fields': ['res_id']})[0]['res_id']
            menus = rpc('ir.ui.menu', 'load_menus', [False])
            assert str(shortcut) in menus, 'HRMS report shortcut must be visible to this payroll user'
            action = rpc('ir.model.data', 'search_read', [[['module', '=', 'hr_payslip_excel_report'],
                ['name', '=', 'hr_payslip_excel_report_action']]], {'fields': ['res_id']})[0]['res_id']
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            batch = rpc('hr.payslip.run', 'create', [{'name': 'Standard Batch Browser Check',
                'company_id': company, 'date_start': '2026-09-01', 'date_end': '2026-09-30'}])
            assert not rpc('ir.model.data', 'search', [[['module', '=', 'hr_payslip_excel_report'],
                ['name', '=', 'menu_draft_payroll_preparation']]])
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            empty_wizard = rpc('payslip.excel.wizard', 'create', [{
                'report_type': 'summary', 'company_id': company, 'duration_type': 'custom',
                'start_date': '2026-10-01', 'end_date': '2026-10-31',
                'employee_ids': [(6, 0, [employee])], 'payslip_status': 'draft',
            }])
            downloads, download_requests = [], []
            page.on('download', lambda item: downloads.append(item))
            page.on('request', lambda item: download_requests.append(item.url)
                    if '/my_excel/download' in item.url else None)
            page.evaluate("""wizard => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type: 'ir.actions.act_window', res_model: 'payslip.excel.wizard',
                res_id: wizard, views: [[false, 'form']], target: 'new'})""", empty_wizard)
            page.evaluate('window.emptyReportWebClient = document.querySelector(".o_web_client")')
            page.get_by_role('button', name='Download Excel', exact=True).click()
            warning = page.get_by_role('dialog').filter(has_text='Generate payslips first')
            warning.wait_for()
            assert 'select Done or All Except Rejected' in warning.inner_text()
            assert page.evaluate('emptyReportWebClient.isConnected')
            assert '/my_excel/download' not in page.url and len(context.pages) == 1
            assert downloads == [] and download_requests == []
            warning.locator('.modal-footer').get_by_role('button', name='Close', exact=True).click()
            page.get_by_role('button', name='Cancel', exact=True).click()
            page.evaluate("""async batch => {
                await odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                    type: 'ir.actions.act_window', res_model: 'hr.payslip.run',
                    res_id: batch, views: [[false, 'form']], target: 'current',
                });
            }""", batch)
            page.get_by_role('button', name='Generate Payslips', exact=True).wait_for()
            assert page.get_by_role('button', name='Prepare Draft Payroll', exact=True).count() == 0
            assert page.get_by_role('button', name='Payroll Report', exact=True).count() == 0
            page.goto(f'{args.url}/odoo/action-{action}')
            page.get_by_role('button', name='Download Excel', exact=True).wait_for()
            report = page.locator('.o_field_widget[name="report_type"] select')
            assert report.locator('option:checked').inner_text() == 'Payslip Summary'
            status = page.locator('.o_field_widget[name="payslip_status"] select')
            assert status.locator('option:checked').inner_text() == 'Draft'
            report.select_option(label='Payroll Review')
            assert status.locator('option:checked').inner_text() == 'Draft'
            page.locator('.o_field_widget[name="duration_type"] select').select_option(label='Custom Date Range')
            page.locator('.o_field_widget[name="start_date"] input').fill('09/01/2026')
            page.locator('.o_field_widget[name="start_date"] input').press('Tab')
            page.locator('.o_field_widget[name="end_date"] input').fill('09/30/2026')
            page.locator('.o_field_widget[name="end_date"] input').press('Tab')
            page.locator('.o_field_widget[name="employee_ids"] input').fill('Payroll Browser Verification')
            page.get_by_role('option', name='Payroll Browser Verification', exact=True).click()
            url = page.url
            page.evaluate('window.originalWebClient = document.querySelector(".o_web_client")')
            with page.expect_download() as download_event:
                page.get_by_role('button', name='Download Excel', exact=True).click()
            download = download_event.value
            assert 'payroll-review-2026-09-01-2026-09-30' in download.suggested_filename
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            download.save_as(args.output)
            assert page.url == url
            assert page.evaluate('originalWebClient.isConnected'), 'The web client was replaced during download'
            with zipfile.ZipFile(io.BytesIO(Path(args.output).read_bytes())) as archive:
                workbook = ET.fromstring(archive.read('xl/workbook.xml'))
                namespace = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                assert [sheet.attrib['name'] for sheet in workbook.findall('s:sheets/s:sheet', namespace)] == [
                    'Payroll Summary', 'Employee Payroll Register', 'Attendance & Adjustments', 'Review Exceptions']
                register = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
                employee_cells = register.findall("s:sheetData/s:row/s:c[@r='B7']", namespace)
                self_panes = register.findall('s:sheetViews/s:sheetView/s:pane', namespace)
                assert len(employee_cells) == 1
                assert register.find("s:sheetData/s:row/s:c[@r='B8']", namespace) is None
                assert not self_panes
                assert b'Duplicate Payslip Excluded' in archive.read('xl/sharedStrings.xml')
                assert workbook.find('s:bookViews/s:workbookView', namespace).attrib['showHorizontalScroll'] == '0'
            report.select_option(label='Payslip Summary')
            with page.expect_download() as summary_event:
                page.get_by_role('button', name='Download Excel', exact=True).click()
            summary_path = Path(args.output).with_name('summary-' + Path(args.output).name)
            summary_event.value.save_as(str(summary_path))
            with zipfile.ZipFile(summary_path) as archive:
                workbook = ET.fromstring(archive.read('xl/workbook.xml'))
                assert [item.attrib['name'] for item in workbook.findall('s:sheets/s:sheet', namespace)] == [
                    'Payslip Summary']
                final = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                assert final.find("s:sheetData/s:row[@r='10']", namespace) is None
                text = archive.read('xl/sharedStrings.xml')
                for label in (b'Salary Type', b'Contract Salary / Rate', b'Paid Weekly-off Days', b'Absent Days',
                              b'Public Holiday Days', b'Public Holiday Worked Days', b'Public Holiday Pay',
                              b'System Overtime', b'System Fine', b'Total Earnings'):
                    assert label in text, label
                sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                assert sheet.find("s:sheetData/s:row/s:c[@r='B8']", namespace) is None
                assert sheet.find('s:sheetViews/s:sheetView/s:pane', namespace) is None
            assert page.evaluate('originalWebClient.isConnected')
            assert not errors, errors
            print('Empty Summary warns in Odoo without navigation/download; standard batch UI, report filters, both XLSX exports and persistent web client: passed')
        finally:
            if empty_wizard:
                rpc('payslip.excel.wizard', 'unlink', [[empty_wizard]])
            if payslips:
                rpc('hr.payslip', 'unlink', [payslips])
            if batch:
                rpc('hr.payslip.run', 'unlink', [[batch]])
            if contract:
                rpc('hr.contract', 'unlink', [[contract]])
            rpc('hr.employee', 'unlink', [[employee]])
            browser.close()


if __name__ == '__main__':
    main()
