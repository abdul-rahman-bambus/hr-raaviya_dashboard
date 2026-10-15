"""Verify the installed combined review and native Odoo deletion/approval flow.

Run against an isolated test database after upgrading the attendance modules:
python bambus_hr_daily_ops/tests/browser/verify_combined_review.py \
    --url http://localhost:8071 --db raaviya_weekly_off_test
Requires Playwright and Chromium. Test fixtures are removed on completion.
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
        parser.error('Use an isolated test database; this check creates test payroll records.')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context = browser.new_context()
        url = args.url
        response = context.request.post(url + '/web/session/authenticate', data={'jsonrpc':'2.0','method':'call',
            'params':{'db':args.db,'login':os.environ.get('ODOO_TEST_LOGIN', 'admin'),'password':os.environ.get('ODOO_TEST_PASSWORD', 'admin')}}).json()
        assert response.get('result',{}).get('uid'), response
        def rpc(model,method,args,kwargs=None):
            result = context.request.post(url+'/web/dataset/call_kw',data={'jsonrpc':'2.0','method':'call',
                'params':{'model':model,'method':method,'args':args,'kwargs':kwargs or {}}}).json()
            assert 'error' not in result, result
            return result['result']
        created = []
        def create(model, values):
            rec = rpc(model,'create',[values]); created.append((model,rec)); return rec
        try:
            cal = create('resource.calendar',{'name':'Unified Browser Calendar','tz':'UTC', 'attendance_ids':[(5,0,0),(0,0,{'name':'Monday','dayofweek':'0','day_period':'morning','hour_from':9,'hour_to':17})]})
            template = create('bambus.attendance.automation.template',{'name':'Unified Browser Rules','break_enabled':True,'overtime_calculation_type':'salary_1_5'})
            employee = create('hr.employee',{'name':'Unified Browser Employee','resource_calendar_id':cal,'attendance_automation_template_id':template})
            contract = create('hr.contract',{'name':'Unified Browser Contract','employee_id':employee,'date_start':'2026-09-01','wage_type':'monthly','wage':3000,'resource_calendar_id':cal})
            for ci,co in [('10:00:00','11:00:00'),('14:00:00','15:00:00')]:
                create('hr.attendance',{'employee_id':employee,'check_in':'2026-09-28 '+ci,'check_out':'2026-09-28 '+co})
            payload = rpc('bambus.hr.attendance.sheet','get_dashboard_review',[employee,'2026-09-28'])
            wizard = payload['wizard_id']
            record = rpc('bambus.hr.attendance.review.wizard','read',[[wizard]],{'fields':['line_id']})[0]
            line = record['line_id'][0]
            rpc('bambus.hr.attendance.sheet.line','write',[[line],{'overtime_hours':1,'overtime_state':'submitted'}])
            wizard = rpc('bambus.hr.attendance.review.wizard','create',[{}],{'context':{'default_line_id':line}})
            view = rpc('ir.model.data','search_read',[[['module','=','bambus_hr_daily_ops'],['name','=','view_attendance_review_wizard']]],{'fields':['res_id']})[0]['res_id']
            action = create('ir.actions.act_window',{'name':'Unified Review Browser Test','res_model':'bambus.hr.attendance.review.wizard','res_id':wizard,'view_mode':'form','view_id':view,'target':'new'})
            page = context.new_page(); errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'{url}/odoo/action-{action}')
            page.get_by_role('button',name='Approve Remaining Items',exact=True).wait_for(timeout=20000)
            assert page.get_by_text('Late Fine',exact=True).count() > 0
            assert page.get_by_text('Break / Gap Fine',exact=True).count() > 0
            assert page.locator('.o_field_widget[name="overtime_hours"]').is_visible()
            # Delete the break row using the actual Odoo list trash control.
            row=page.locator('tr.o_data_row').filter(has_text='Break / Gap Fine')
            row.locator('.o_list_record_remove button, .o_list_record_remove').first.click()
            page.get_by_role('button',name='Approve Remaining Items',exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            record=rpc('bambus.hr.attendance.sheet.line','read',[[line]],{'fields':['overtime_state','fine_state','fine_review_data']})[0]
            assert record['overtime_state']=='approved', record
            assert record['fine_review_data']['break']['state']=='ignored',record
            assert not errors, errors
            print('PASS: actual Odoo combined form renders OT and separate fines, native trash ignores break, one approval saves all remaining items.')
        finally:
            # The disposable DB is dedicated to tests; remove the day line before its employee.
            lines=rpc('bambus.hr.attendance.sheet.line','search',[[['employee_id','=',employee]]]) if 'employee' in locals() else []
            if lines: rpc('bambus.hr.attendance.sheet.line','unlink',[lines])
            for model,rec in reversed(created):
                rpc(model,'unlink',[[rec]])
            browser.close()


if __name__ == '__main__':
    main()
