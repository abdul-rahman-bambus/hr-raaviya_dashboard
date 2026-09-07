from odoo import fields
from odoo.exceptions import UserError
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
        self.assertEqual(roster[employee.id]["logs"], [])
        self.assertFalse(roster[employee.id]["is_hourly"])
        self.assertGreaterEqual(dashboard["metrics"]["not_marked"], 1)
        self.assertEqual(dashboard["metrics"]["absent"], 0)

    def test_hourly_employee_cannot_be_marked_absent(self):
        contract_model = self.env["hr.contract"]
        if "wage_type" not in contract_model._fields:
            self.skipTest("The installed payroll module does not provide contract wage types.")
        employee = self.env["hr.employee"].create({
            "name": "Hourly Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        contract_model.create({
            "name": "Hourly Employee Contract",
            "employee_id": employee.id,
            "date_start": today,
            "wage": 10,
            "wage_type": "hourly",
        })

        dashboard = self.env["bambus.hr.attendance.sheet"].get_attendance_dashboard(
            selected_date=fields.Date.to_string(today),
        )
        roster = {item["id"]: item for item in dashboard["daily_attendance"]}
        self.assertTrue(roster[employee.id]["is_hourly"])
        with self.assertRaisesRegex(UserError, "Hourly employees cannot be marked absent"):
            self.env["bambus.hr.attendance.sheet"].update_dashboard_attendance(
                employee.id,
                fields.Date.to_string(today),
                {"status": "absent"},
            )
