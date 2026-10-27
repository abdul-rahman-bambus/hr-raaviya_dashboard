from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestAttendanceEntryNavigation(TransactionCase):
    def test_employee_and_local_date_domain_match_dashboard(self):
        user = new_test_user(self.env, login='entry_navigation_hr',
            groups='hr_attendance.group_hr_attendance_manager,hr.group_hr_user', tz='Asia/Kolkata')
        employee = self.env['hr.employee'].create({'name': 'Navigation employee'})
        other = self.env['hr.employee'].create({'name': 'Other navigation employee'})
        expected = self.env['hr.attendance']
        for worker, start, end in [
            (employee, '2026-10-21 18:00:00', '2026-10-21 18:29:59'),
            (employee, '2026-10-21 18:30:00', '2026-10-21 19:00:00'),
            (employee, '2026-10-22 18:00:00', '2026-10-22 18:29:59'),
            (employee, '2026-10-22 18:30:00', '2026-10-22 19:00:00'),
            (other, '2026-10-22 04:15:00', '2026-10-22 06:30:00')]:
            punch = self.env['hr.attendance'].create({'employee_id': worker.id,
                'check_in': start, 'check_out': end})
            if worker == employee and start in ('2026-10-21 18:30:00', '2026-10-22 18:00:00'):
                expected |= punch
        action = self.env['bambus.attendance.dashboard'].with_user(user).open_dashboard_attendance_entries(
            employee.id, '2026-10-22')
        self.assertEqual(action['res_model'], 'hr.attendance')
        self.assertEqual(action['context']['default_employee_id'], employee.id)
        self.assertEqual(self.env['hr.attendance'].with_user(user).search(action['domain']), expected)

    def test_empty_day_opens_list_and_dst_bounds_cover_one_local_day(self):
        user = new_test_user(self.env, login='entry_navigation_dst',
            groups='hr_attendance.group_hr_attendance_manager,hr.group_hr_user', tz='Europe/London')
        employee = self.env['hr.employee'].create({'name': 'Empty day navigation'})
        action = self.env['bambus.attendance.dashboard'].with_user(user).open_dashboard_attendance_entries(
            employee.id, '2026-03-29')
        bounds = {operator: value for field, operator, value in action['domain'] if field == 'check_in'}
        self.assertEqual(bounds, {'>=': '2026-03-29 00:00:00', '<': '2026-03-29 23:00:00'})
        self.assertFalse(self.env['hr.attendance'].search(action['domain']))

    def test_navigation_does_not_bypass_attendance_access(self):
        user = new_test_user(self.env, login='entry_navigation_no_access', groups='base.group_user')
        employee = self.env['hr.employee'].create({'name': 'Protected navigation'})
        with self.assertRaises(AccessError):
            self.env['bambus.attendance.dashboard'].with_user(user).open_dashboard_attendance_entries(
                employee.id, '2026-10-22')
