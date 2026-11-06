"""Installed read-only employee attendance, daily parity and HR navigation; test DB only."""
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
            calendar = create('resource.calendar', {'name': 'Employee parity browser calendar', 'tz': 'UTC',
                'attendance_ids': [(5, 0, 0)] + [(0, 0, {'name': period, 'dayofweek': str(day),
                    'day_period': period, 'hour_from': start, 'hour_to': end}) for day in range(6)
                    for period, start, end in [('morning', 9.75, 14), ('afternoon', 14.75, 18.75)]]})
            template = create('bambus.attendance.automation.template', {'name': 'Employee parity browser template',
                'partial_attendance_salary_treatment': 'fine_only', 'late_enabled': True, 'late_grace_minutes': 5,
                'post_break_grace_minutes': 0, 'early_exit_enabled': True, 'break_enabled': True,
                'overtime_enabled': True, 'overtime_end_mode': 'duration', 'maximum_overtime_minutes': 60})
            employee = create('hr.employee', {'name': 'Employee Parity Browser',
                'resource_calendar_id': calendar, 'attendance_automation_template_id': template})
            create('hr.contract', {'name': 'Employee parity browser contract', 'employee_id': employee,
                'date_start': '2026-11-01', 'resource_calendar_id': calendar,
                'wage_type': 'daily', 'daily_wage': 885, 'wage': 0})
            punches = []
            for start, end in [('2026-11-05 09:51:00', '2026-11-05 14:00:00'),
                               ('2026-11-05 14:50:00', '2026-11-06 00:16:00'),
                               ('2026-11-06 09:57:00', False)]:
                punches.append(create('hr.attendance', {'employee_id': employee, 'check_in': start, 'check_out': end}))
            review = create('bambus.attendance.day.review', {'employee_id': employee, 'date': '2026-11-05',
                'fine_hours': 0, 'overtime_hours': 0})
            def monthly():
                return rpc('hr.employee', 'get_monthly_attendance', [employee, '2026-11'])
            payload = monthly()
            day = next(row for row in payload['rows'] if row['date'] == '2026-11-05')
            daily = next(row for row in rpc('bambus.attendance.dashboard', 'get_attendance_dashboard', ['2026-11-05'])['daily_attendance'] if row['id'] == employee)
            assert day['fine_hours'] == daily['fine_hours'] == .1, (day, daily)
            assert day['overtime_hours'] == daily['overtime_hours'] == 1, (day, daily)
            assert day['check_out_day_offset'] == 1 and day['check_out_date'] == '2026-11-06'
            rpc('bambus.attendance.day.review', 'write', [[review], {'overtime_state':'rejected','overtime_hours':0}])
            snapshots = rpc('bambus.attendance.day.review', 'read', [[review], ['fine_state','fine_hours','fine_amount','overtime_state','overtime_hours','overtime_amount']])
            raw = rpc('hr.attendance', 'read', [punches, ['check_in','check_out','worked_hours']])
            page = context.new_page()
            page.set_viewport_size({'width': 1920, 'height': 1080})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url + '/odoo?debug=assets')
            page.wait_for_selector('.o_web_client', timeout=60000)
            page.evaluate("""id => odoo.__WOWL_DEBUG__.root.env.services.action.doAction({type:'ir.actions.client',
                tag:'bambus_employee_attendance',params:{employee_id:id}})""", employee)
            month = page.get_by_label('Select month', exact=True)
            month.fill('2026-11')
            month.dispatch_event('change')
            cards = page.locator('.o_bea_day')
            expect(cards).to_have_count(2)
            expect(cards.first).to_contain_text('(+1 day)')
            expect(cards.first).to_contain_text('0:06 Hrs')
            expect(cards.first).to_contain_text('Needs Review')
            expect(cards.first).to_contain_text('Excluded')
            expect(cards.last).to_contain_text('0:07 Hrs')
            expect(cards.last).to_contain_text('Punched In')
            expect(page.get_by_role('status')).to_have_count(0)
            assert page.locator('button.o_bea_detail.leave').count() == 0
            page.screenshot(path='work/employee-attendance-readonly.png', full_page=True)
            cards.first.get_by_role('button', name='Open Daily Dashboard', exact=True).click()
            expect(page.locator('.o_bae_employee')).to_have_count(1)
            expect(page.locator('input[type=date]')).to_have_value('2026-11-05')
            expect(page.locator('.o_bae_employee')).to_contain_text('Employee Parity Browser')
            assert rpc('hr.attendance', 'read', [punches, ['check_in','check_out','worked_hours']]) == raw
            assert rpc('bambus.attendance.day.review', 'read', [[review], ['fine_state','fine_hours','fine_amount','overtime_state','overtime_hours','overtime_amount']]) == snapshots
            assert not errors, errors
            print('PASS: employee view matches live daily detection, shows saved exclusion/open late/overnight markers, remains read-only and links HR to the exact employee/date.')
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
