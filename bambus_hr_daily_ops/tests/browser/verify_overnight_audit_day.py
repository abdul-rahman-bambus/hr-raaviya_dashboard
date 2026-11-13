"""Installed overnight audit grouping for empty attendance days; test DB only; test DB only."""
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

        try:
            calendar=create('resource.calendar',{'name':'Overnight audit browser calendar','tz':'Asia/Kolkata'})
            people=create('hr.employee',[{'name':'Overnight audit browser %02d'%index,
                'resource_calendar_id':calendar,'tz':'Asia/Kolkata'} for index in range(19)])
            create('hr.contract',[{'name':'Overnight audit contract','employee_id':employee,
                'resource_calendar_id':calendar,'date_start':'2026-11-01',
                'wage_type':'daily','wage':0,'daily_wage':885} for employee in people])
            punches=create('hr.attendance',[{'employee_id':employee,'check_in':'2026-11-12 09:18:00'} for employee in people])
            for punch in punches:
                rpc('hr.attendance','write',[[punch],{'check_out':'2026-11-12 23:59:59'}])
                rpc('hr.attendance','write',[[punch],{'check_out':'2026-11-12 14:30:00','out_mode':'auto_check_out'}])
            audit_domain=[['employee_id','in',people],['date','=','2026-11-13'],['event_source','=','manual']]
            audit_ids=rpc('bambus.hr.attendance.time.audit','search',[audit_domain])
            assert len(audit_ids)==19,audit_ids
            data=rpc('bambus.attendance.dashboard','get_attendance_dashboard',[],{
                'selected_date':'2026-11-13','query':'Overnight audit browser','context':{'tz':'Asia/Kolkata'}})
            assert len(data['daily_attendance'])==19
            assert all(not row['logs'] and row['status']=='not_marked' for row in data['daily_attendance'])
            page=context.new_page()
            page.set_viewport_size({'width':1920,'height':1080})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(args.url+'/odoo?debug=assets')
            page.wait_for_selector('.o_web_client',timeout=60000)
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type:'ir.actions.client',tag:'bambus_attendance_editor',params:{
                selected_date:'2026-11-13',employee_query:'Overnight audit browser'}})""")
            cards=page.locator('.o_bae_employee')
            expect(cards).to_have_count(19,timeout=60000)
            logs=cards.locator('.o_bae_links button').filter(has_text=re.compile(r'^\s*Logs\s*$'))
            expect(logs).to_have_count(19)
            logs.first.click()
            expect(page.locator('.o_bea_no_logs')).to_be_visible()
            assert rpc('bambus.hr.attendance.time.audit','search',[audit_domain])==audit_ids
            assert not errors,errors
            print('PASS: native 23:59 UTC historical adjustment reproduced for 19 employees; empty next day has zero logs, popup is empty, all 19 manual audit rows retained.')
        finally:
            for model,record in reversed(created):
                rpc(model,'unlink',[record if isinstance(record,list) else [record]])
            browser.close()


if __name__ == '__main__':
    main()
