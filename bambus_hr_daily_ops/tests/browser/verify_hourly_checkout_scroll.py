"""Installed hourly checkout settings and server-backed infinite scroll; test DB only."""
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
            template = create('bambus.attendance.automation.template', {
                'name':'Scroll checkout browser template', 'hourly_auto_checkout_enabled':False})
            people = create('hr.employee', [{'name':'Scroll browser %03d' % index,
                'resource_calendar_id':False, 'attendance_automation_template_id':template}
                for index in range(60)])
            # Completed entries exercise the populated date, not just an empty roster.
            create('hr.attendance', [{'employee_id':employee, 'check_in':'2026-11-12 09:00:00',
                'check_out':'2026-11-12 17:00:00'} for employee in people])
            page = context.new_page()
            page.set_viewport_size({'width':1920,'height':1080})
            errors=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url+'/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""id => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type:'ir.actions.act_window',res_model:'bambus.attendance.automation.template',
                res_id:id,views:[[false,'form']],target:'current'})""", template)
            page.get_by_role('tab',name='Hourly Pay',exact=True).click()
            enabled=page.locator('.o_field_widget[name="hourly_auto_checkout_enabled"] input')
            basis=page.locator('.o_field_widget[name="hourly_auto_checkout_basis"] select')
            expect(enabled).not_to_be_checked()
            expect(basis).not_to_be_visible()
            enabled.check()
            expect(basis).to_be_visible()
            basis.select_option(label='Fixed Daily Time')
            fixed=page.locator('.o_field_widget[name="hourly_auto_checkout_time"] input')
            expect(fixed).to_be_visible()
            fixed.fill('20:00')
            fixed.press('Tab')
            page.locator('.o_form_button_save').click()
            expect(page.locator('.o_form_button_save')).not_to_be_visible()
            values=rpc('bambus.attendance.automation.template','read',[[template]],
                {'fields':['hourly_auto_checkout_enabled','hourly_auto_checkout_basis','hourly_auto_checkout_time']})[0]
            assert values['hourly_auto_checkout_enabled'] and values['hourly_auto_checkout_basis']=='time',values
            assert values['hourly_auto_checkout_time']==20,values
            page.evaluate("""() => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({
                type:'ir.actions.client',tag:'bambus_attendance_editor',params:{
                selected_date:'2026-11-12',employee_query:'Scroll browser'}})""")
            cards=page.locator('.o_bae_employee')
            expect(cards).to_have_count(25,timeout=60000)
            first=cards.first.locator('.o_bae_employee_info strong').inner_text()
            summary=page.locator('.o_bad_editor_metrics').inner_text()
            page.locator('.o_bambus_attendance_dashboard').evaluate('el => el.scrollTop=el.scrollHeight')
            expect(cards).to_have_count(50,timeout=60000)
            assert cards.first.locator('.o_bae_employee_info strong').inner_text()==first
            assert page.locator('.o_bad_editor_metrics').inner_text()==summary
            page.locator('.o_bambus_attendance_dashboard').evaluate('el => el.scrollTop=el.scrollHeight')
            expect(cards).to_have_count(60,timeout=60000)
            search=page.get_by_placeholder('Search Staff by Name, Department or Schedule')
            search.fill('Scroll browser 059')
            expect(cards).to_have_count(1,timeout=60000)
            expect(cards.first).to_contain_text('Scroll browser 059')
            assert not errors,errors
            print('PASS: hourly template opt-in and fixed time save; populated day scrolls 25/50/60 with stable company totals; server search finds last employee.')
        finally:
            for model,record in reversed(created):
                rpc(model,'unlink',[record if isinstance(record,list) else [record]])
            browser.close()


if __name__ == '__main__':
    main()
