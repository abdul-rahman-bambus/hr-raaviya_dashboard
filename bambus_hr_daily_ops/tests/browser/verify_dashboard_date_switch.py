"""Installed populated-date switching and fresh policy inputs; test DB only; test DB only."""
import argparse
import os
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
            calendar=create('resource.calendar',{'name':'Date switch browser calendar','tz':'UTC',
                'attendance_ids':[(5,0,0)]+[(0,0,{'name':'Work','dayofweek':str(day),
                'day_period':'morning','hour_from':9.75,'hour_to':17}) for day in range(6)]})
            template=create('bambus.attendance.automation.template',{'name':'Date switch browser policy',
                'partial_attendance_salary_treatment':'fine_only','late_enabled':True,
                'late_grace_minutes':5,'early_exit_enabled':False,'break_enabled':False})
            people=create('hr.employee',[{'name':'Date switch browser %02d'%index,
                'resource_calendar_id':calendar,'attendance_automation_template_id':template} for index in range(19)])
            create('hr.contract',[{'name':'Date switch contract','employee_id':employee,
                'resource_calendar_id':calendar,'date_start':'2026-11-01',
                'wage_type':'daily','wage':0,'daily_wage':885} for employee in people])
            create('hr.attendance',[{'employee_id':employee,'check_in':'2026-11-%s 09:%s:00'%(day,minute),
                'check_out':'2026-11-%s 17:00:00'%day} for employee in people
                for day,minute in [('11','55'),('12','51')]])
            page=context.new_page()
            page.set_viewport_size({'width':1920,'height':1080})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(args.url+'/odoo?debug=assets')
            page.wait_for_selector('.o_web_client',timeout=60000)
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type:'ir.actions.client',tag:'bambus_attendance_editor',params:{
                selected_date:'2026-11-12',employee_query:'Date switch browser'}})""")
            cards=page.locator('.o_bae_employee')
            expect(cards).to_have_count(19,timeout=60000)
            expect(cards.first.locator('.fine strong')).to_have_text('0h 01m')
            page.evaluate("window.dateSwitchOriginalCard=document.querySelector('.o_bae_employee')")
            page.get_by_title('Previous day',exact=True).click()
            expect(cards.first.locator('.fine strong')).to_have_text('0h 05m',timeout=60000)
            assert page.evaluate('dateSwitchOriginalCard.isConnected')
            rpc('bambus.attendance.automation.template','write',[[template],{'late_grace_minutes':0}])
            page.get_by_title('Next day',exact=True).click()
            expect(cards.first.locator('.fine strong')).to_have_text('0h 06m',timeout=60000)
            assert page.evaluate('dateSwitchOriginalCard.isConnected')
            assert not errors,errors
            print('PASS: 19 populated employee cards switch dates without replacing card nodes; fine changes 1 to 5 minutes; next read sees changed grace and shows 6 minutes.')
        finally:
            for model,record in reversed(created):
                rpc(model,'unlink',[record if isinstance(record,list) else [record]])
            browser.close()


if __name__ == '__main__':
    main()
