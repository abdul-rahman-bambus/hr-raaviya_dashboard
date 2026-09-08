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

    def test_half_day_action_creates_and_confirms_unpaid_leave(self):
        employee = self.env["hr.employee"].create({
            "name": "Half Day Employee",
            "company_id": self.env.company.id,
        })
        leave_type = self.env.ref(
            "hr_holidays.holiday_status_unpaid", raise_if_not_found=False
        )
        if not leave_type:
            leave_type = self.env["hr.leave.type"].create({
                "name": "Unpaid",
                "requires_allocation": "no",
            })
        today = fields.Date.context_today(employee)

        result = self.env["bambus.hr.attendance.sheet"].create_half_day_leave(
            employee.id,
            fields.Date.to_string(today),
        )

        leave = self.env["hr.leave"].browse(result["leave_id"])
        self.assertEqual(leave.employee_id, employee)
        self.assertEqual(leave.holiday_status_id, leave_type)
        self.assertTrue(leave.request_unit_half)
        self.assertEqual(leave.request_date_from_period, "am")
        self.assertEqual(leave.state, "confirm")

        self.env["bambus.hr.attendance.sheet"].revoke_dashboard_status(
            employee.id,
            fields.Date.to_string(today),
            "halfday",
        )
        self.assertFalse(leave.exists())
        sheet = self.env["bambus.hr.attendance.sheet"].search([
            ("date", "=", today),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        self.assertFalse(sheet.line_ids.filtered(lambda line: line.employee_id == employee))

    def test_absent_status_can_be_revoked(self):
        employee = self.env["hr.employee"].create({
            "name": "Revoked Absence Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        attendance_sheet = self.env["bambus.hr.attendance.sheet"]
        attendance_sheet.update_dashboard_attendance(
            employee.id,
            fields.Date.to_string(today),
            {"status": "absent"},
        )

        attendance_sheet.revoke_dashboard_status(
            employee.id,
            fields.Date.to_string(today),
            "absent",
        )

        dashboard = attendance_sheet.get_attendance_dashboard(fields.Date.to_string(today))
        roster = {item["id"]: item for item in dashboard["daily_attendance"]}
        self.assertEqual(roster[employee.id]["status"], "not_marked")

    def test_full_day_leave_can_be_revoked(self):
        employee = self.env["hr.employee"].create({
            "name": "Full Day Leave Employee",
            "company_id": self.env.company.id,
        })
        leave_type = self.env.ref(
            "hr_holidays.holiday_status_unpaid", raise_if_not_found=False
        ) or self.env["hr.leave.type"].create({
            "name": "Unpaid",
            "requires_allocation": "no",
        })
        today = fields.Date.context_today(employee)
        leave = self.env["hr.leave"].create({
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": today,
            "request_date_to": today,
            "name": "Full Day Leave",
        })
        leave.action_confirm()

        self.env["bambus.hr.attendance.sheet"].revoke_dashboard_status(
            employee.id,
            fields.Date.to_string(today),
            "leave",
        )

        self.assertFalse(leave.exists())
