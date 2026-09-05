from odoo import fields
from odoo.tests.common import TransactionCase


class TestAttendanceDashboard(TransactionCase):

    def test_active_employee_without_punch_is_in_daily_roster(self):
        employee = self.env["hr.employee"].create({
            "name": "Employee Without Attendance",
            "company_id": self.env.company.id,
        })

        dashboard = self.env["bambus.hr.attendance.sheet"].get_attendance_dashboard(
            selected_date=fields.Date.to_string(fields.Date.context_today(employee)),
        )

        roster = {item["id"]: item for item in dashboard["daily_attendance"]}
        self.assertIn(employee.id, roster)
        self.assertEqual(roster[employee.id]["status"], "not_marked")
        self.assertFalse(roster[employee.id]["check_in"])
        self.assertFalse(roster[employee.id]["check_out"])
