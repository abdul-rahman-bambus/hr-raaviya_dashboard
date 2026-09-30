from datetime import datetime, time, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestAttendanceDashboard(TransactionCase):

    def _sheet_for(self, day):
        """Reuse a pre-existing daily sheet when tests run on a populated DB."""
        sheet_model = self.env["bambus.hr.attendance.sheet"]
        return sheet_model.search([
            ("date", "=", day),
            ("company_id", "=", self.env.company.id),
        ], limit=1) or sheet_model.create({
            "date": day,
            "company_id": self.env.company.id,
        })

    def _unpaid_leave_type(self, employee):
        """Return an active unpaid type that is valid for the employee company."""
        leave_type = self.env.ref(
            "hr_holidays.holiday_status_unpaid", raise_if_not_found=False
        )
        if leave_type and (
            not leave_type.active
            or (leave_type.company_id and leave_type.company_id != employee.company_id)
        ):
            leave_type = False
        return leave_type or self.env["hr.leave.type"].search([
            ("active", "=", True),
            ("name", "ilike", "unpaid"),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", employee.company_id.id),
        ], limit=1) or self.env["hr.leave.type"].create({
            "name": "Unpaid",
            "requires_allocation": "no",
            "company_id": employee.company_id.id,
        })

    def test_overtime_salary_slabs_resolve_contract_wage_boundaries(self):
        template = self.env["bambus.attendance.automation.template"].create({
            "name": "Salary Slab Rules",
            "company_id": self.env.company.id,
            "overtime_rate_policy": "salary_slab",
            # Keep the wizard assertion deterministic on populated databases
            # where today's date may already be configured as a public holiday.
            "public_holiday_rate_policy": "salary_slab",
            "public_holiday_calculation_type": "fixed_hour",
            "overtime_salary_basis": "monthly",
            "overtime_slab_ids": [
                (0, 0, {"salary_from": 0, "salary_to": 9000, "rate": 75}),
                (0, 0, {"salary_from": 9000.01, "salary_to": 12000, "rate": 100}),
                (0, 0, {"salary_from": 12000.01, "has_maximum": False, "rate": 120}),
            ],
        })
        employee = self.env["hr.employee"].create({
            "name": "Salary Slab Employee",
            "company_id": self.env.company.id,
        })
        contract = self.env["hr.contract"].create({
            "name": "Salary Slab Contract",
            "employee_id": employee.id,
            "date_start": fields.Date.context_today(employee),
            "wage": 9000,
        })

        self.assertEqual(template.resolve_overtime_rate(contract)[0], 75)
        contract.wage = 9000.01
        self.assertEqual(template.resolve_overtime_rate(contract)[0], 100)
        contract.wage = 12000
        self.assertEqual(template.resolve_overtime_rate(contract)[0], 100)
        contract.wage = 12000.01
        self.assertEqual(template.resolve_overtime_rate(contract)[0], 120)

        contract.wage = 10000
        employee.attendance_automation_template_id = template
        sheet = self._sheet_for(fields.Date.context_today(employee))
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "contract_id": contract.id,
            "overtime_hours": 2,
            "overtime_state": "submitted",
        })
        wizard_model = self.env["bambus.hr.overtime.wizard"].with_context(
            default_line_id=line.id
        )
        defaults = wizard_model.default_get([
            "line_id", "detected_overtime_hours", "overtime_hours",
            "calculation_type", "rate", "resolved_rate", "automation_template_id",
            "salary_basis_amount", "overtime_slab_id", "rate_resolution_warning",
        ])
        wizard = wizard_model.create(defaults)
        self.assertEqual(wizard.rate, 100)
        self.assertEqual(wizard.overtime_amount, 200)
        wizard.action_save()
        self.assertEqual(line.overtime_salary_basis_amount, 10000)
        self.assertEqual(line.overtime_slab_id.rate, 100)
        self.assertEqual(line.overtime_amount, 200)

    def test_overtime_salary_slabs_cannot_overlap(self):
        template = self.env["bambus.attendance.automation.template"].create({
            "name": "Invalid Salary Slab Rules",
            "company_id": self.env.company.id,
            "overtime_rate_policy": "salary_slab",
        })
        slab_model = self.env["bambus.attendance.overtime.rate.slab"]
        slab_model.create({
            "template_id": template.id,
            "salary_from": 0,
            "salary_to": 9000,
            "rate": 75,
        })
        with self.assertRaises(ValidationError):
            slab_model.create({
                "template_id": template.id,
                "salary_from": 8500,
                "salary_to": 12000,
                "rate": 100,
            })

    def test_employee_automation_template_overrides_company_default(self):
        today = fields.Date.context_today(self.env.user)
        template_model = self.env["bambus.attendance.automation.template"]
        company_template = template_model.create({
            "name": "Company Rules",
            "company_id": self.env.company.id,
            "minimum_overtime_minutes": 30,
        })
        employee_template = template_model.create({
            "name": "Employee Rules",
            "company_id": self.env.company.id,
            "minimum_overtime_minutes": 15,
            "overtime_calculation_type": "salary_1_5",
        })
        self.env.company.attendance_automation_template_id = company_template
        employee = self.env["hr.employee"].create({
            "name": "Template Employee",
            "company_id": self.env.company.id,
            "attendance_automation_template_id": employee_template.id,
        })

        self.assertEqual(
            employee._get_attendance_automation_template(today), employee_template
        )
        employee.attendance_automation_template_id = False
        self.assertEqual(
            employee._get_attendance_automation_template(today), company_template
        )

        assignment_employee = self.env["hr.employee"].create({
            "name": "Wizard Assignment Employee",
            "company_id": self.env.company.id,
        })
        wizard = self.env["bambus.attendance.automation.assign.wizard"].create({
            "template_id": employee_template.id,
            "employee_ids": [(6, 0, assignment_employee.ids)],
        })
        wizard.action_assign()
        self.assertEqual(
            assignment_employee.attendance_automation_template_id,
            employee_template,
        )

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

    def test_review_line_without_punch_does_not_create_presence_or_fine(self):
        employee = self.env["hr.employee"].create({
            "name": "Review Only Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        sheet_model = self.env["bambus.hr.attendance.sheet"]

        action = sheet_model.open_dashboard_adjustment(
            employee.id, fields.Date.to_string(today), "fine"
        )
        line = self.env["bambus.hr.attendance.sheet.line"].browse(
            action["context"]["default_line_id"]
        )
        # Simulate stale values from a previously opened/incomplete review.
        line.write({"status": "present", "fine_hours": 8})

        dashboard = sheet_model.get_attendance_dashboard(fields.Date.to_string(today))
        row = next(item for item in dashboard["daily_attendance"] if item["id"] == employee.id)
        self.assertEqual(row["status"], "not_marked")
        self.assertFalse(row["has_attendance"])
        self.assertEqual(row["fine_hours"], 0)

    def test_incomplete_manual_time_is_not_present_or_fined(self):
        employee = self.env["hr.employee"].create({
            "name": "Incomplete Manual Time Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        sheet_model = self.env["bambus.hr.attendance.sheet"]

        result = sheet_model.update_dashboard_attendance(
            employee.id,
            fields.Date.to_string(today),
            {
                "status": "not_marked",
                "status_manual": False,
                "check_in": "14:46",
            },
        )
        self.assertEqual(result["status"], "not_marked")

        dashboard = sheet_model.get_attendance_dashboard(fields.Date.to_string(today))
        row = next(item for item in dashboard["daily_attendance"] if item["id"] == employee.id)
        self.assertEqual(row["status"], "not_marked")
        self.assertEqual(row["check_in_value"], "14:46")
        self.assertFalse(row["check_out_value"])
        self.assertEqual(row["fine_hours"], 0)

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

    def test_hourly_template_enables_pay_review_with_contract_rate(self):
        today = fields.Date.context_today(self.env.user)
        template = self.env["bambus.attendance.automation.template"].create({
            "name": "Hourly Pay Review",
            "company_id": self.env.company.id,
            "hourly_pay_enabled": True,
            "hourly_pay_calculation_type": "salary_1",
        })
        employee = self.env["hr.employee"].create({
            "name": "Hourly Pay Review Employee",
            "company_id": self.env.company.id,
            "attendance_automation_template_id": template.id,
        })
        contract = self.env["hr.contract"].create({
            "name": "Hourly Pay Review Contract",
            "employee_id": employee.id,
            "company_id": self.env.company.id,
            "date_start": today,
            "wage_type": "hourly",
            "hourly_rate": 25,
            "wage": 0,
        })
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": self._sheet_for(today).id,
            "employee_id": employee.id,
            "contract_id": contract.id,
            "worked_hours": 7.5,
        })
        wizard_model = self.env["bambus.hr.hourly.pay.wizard"].with_context(
            default_line_id=line.id
        )
        wizard = wizard_model.create(wizard_model.default_get([
            "line_id", "detected_hourly_pay_hours", "hourly_pay_hours",
            "calculation_type", "rate", "note",
        ]))

        self.assertEqual(wizard.detected_hourly_pay_hours, 7.5)
        self.assertEqual(wizard.calculation_type, "salary_1")
        self.assertEqual(wizard.hourly_pay_amount, 187.5)
        wizard.hourly_pay_hours = 7
        wizard.action_save()
        self.assertEqual(line.hourly_pay_state, "approved")
        self.assertEqual(line.hourly_pay_hours, 7)
        self.assertEqual(line.hourly_pay_amount, 175)

    def test_half_day_action_creates_and_confirms_unpaid_leave(self):
        employee = self.env["hr.employee"].create({
            "name": "Half Day Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)

        result = self.env["bambus.hr.attendance.sheet"].create_half_day_leave(
            employee.id,
            fields.Date.to_string(today),
        )

        leave = self.env["hr.leave"].browse(result["leave_id"])
        self.assertEqual(leave.employee_id, employee)
        self.assertIn("unpaid", leave.holiday_status_id.name.lower())
        self.assertTrue(
            not leave.holiday_status_id.company_id
            or leave.holiday_status_id.company_id == employee.company_id
        )
        self.assertTrue(leave.request_unit_half)
        self.assertEqual(leave.request_date_from_period, "am")
        self.assertIn(leave.state, ("confirm", "validate1", "validate"))

        self.env["bambus.hr.attendance.sheet"].revoke_dashboard_status(
            employee.id,
            fields.Date.to_string(today),
            "halfday",
        )
        self.assertTrue(leave.exists())
        self.assertEqual(leave.state, "cancel")
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
        result = attendance_sheet.update_dashboard_attendance(
            employee.id,
            fields.Date.to_string(today),
            {"status": "absent"},
        )
        self.assertEqual(result["status"], "absent")
        self.assertTrue(result["line_id"])
        self.assertEqual(result["worked_hours"], 0.0)

        attendance_sheet.revoke_dashboard_status(
            employee.id,
            fields.Date.to_string(today),
            "absent",
        )

        dashboard = attendance_sheet.get_attendance_dashboard(fields.Date.to_string(today))
        roster = {item["id"]: item for item in dashboard["daily_attendance"]}
        self.assertEqual(roster[employee.id]["status"], "not_marked")

    def test_hr_can_update_overtime_and_fine_from_editor(self):
        employee = self.env["hr.employee"].create({
            "name": "Overtime Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        attendance_sheet = self.env["bambus.hr.attendance.sheet"]

        attendance_sheet.update_dashboard_attendance(
            employee.id,
            fields.Date.to_string(today),
            {
                "status": "present",
                "overtime_hours": 1.5,
                "fine_hours": 0.25,
            },
        )

        dashboard = attendance_sheet.get_attendance_dashboard(
            fields.Date.to_string(today)
        )
        row = next(
            item for item in dashboard["daily_attendance"]
            if item["id"] == employee.id
        )
        self.assertEqual(row["overtime_hours"], 1.5)
        self.assertEqual(row["fine_hours"], 0.25)
        self.assertGreaterEqual(dashboard["metrics"]["overtime"], 1.5)
        self.assertGreaterEqual(dashboard["metrics"]["fine"], 0.25)

    def test_attendance_logs_include_hr_time_updates(self):
        employee = self.env["hr.employee"].create({
            "name": "HR Time Update Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        sheet_model = self.env["bambus.hr.attendance.sheet"]

        sheet_model.update_dashboard_attendance(
            employee.id,
            fields.Date.to_string(today),
            {"status": "present", "check_in": "09:15", "check_out": "17:45"},
        )
        dashboard = sheet_model.get_attendance_dashboard(fields.Date.to_string(today))
        row = next(
            item for item in dashboard["daily_attendance"]
            if item["id"] == employee.id
        )
        hr_log = next(log for log in row["logs"] if log["type"] == "hr_update")

        self.assertEqual(hr_log["actor"], self.env.user.name)
        self.assertIn("In ", hr_log["details"])
        self.assertIn("Out ", hr_log["details"])

    def test_dashboard_opens_ot_and_fine_updates_without_history(self):
        employee = self.env["hr.employee"].create({
            "name": "Direct Dashboard Review Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        sheet_model = self.env["bambus.hr.attendance.sheet"]

        overtime_action = sheet_model.open_dashboard_adjustment(
            employee.id, fields.Date.to_string(today), "overtime"
        )
        line_id = overtime_action["context"]["default_line_id"]
        self.assertEqual(overtime_action["res_model"], "bambus.hr.overtime.wizard")
        self.assertEqual(overtime_action["views"][0][1], "form")
        self.assertTrue(line_id)

        fine_action = sheet_model.open_dashboard_adjustment(
            employee.id, fields.Date.to_string(today), "fine"
        )
        self.assertEqual(fine_action["res_model"], "bambus.hr.fine.wizard")
        self.assertEqual(fine_action["views"][0][1], "form")
        self.assertEqual(fine_action["context"]["default_line_id"], line_id)

        editor = sheet_model.get_dashboard_adjustment(
            employee.id, fields.Date.to_string(today), "overtime"
        )
        self.assertEqual(editor["employee"], employee.name)
        self.assertEqual(editor["adjustment"], "overtime")
        self.assertTrue(editor["wizard_id"])
        self.assertNotIn("sheet_id", editor)
        self.assertNotIn("template_id", editor)
        sheet_model.save_dashboard_adjustment(
            editor["wizard_id"],
            "overtime",
            {
                "hours": 0,
                "calculation_type": "regularize",
                "rate": 0,
                "note": "Reviewed from dashboard",
            },
        )
        line = self.env["bambus.hr.attendance.sheet.line"].browse(line_id)
        self.assertEqual(line.overtime_state, "approved")
        self.assertEqual(line.overtime_note, "Reviewed from dashboard")

        with self.assertRaises(UserError):
            sheet_model.open_dashboard_adjustment(
                employee.id, fields.Date.to_string(today), "unsupported"
            )

    def test_hr_saves_overtime_calculation(self):
        employee = self.env["hr.employee"].create({
            "name": "Overtime Approval Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        contract = self.env["hr.contract"].create({
            "name": "Overtime Approval Contract",
            "employee_id": employee.id,
            "date_start": today,
            "wage": 24000,
            "overtime_rate": 75,
            "is_overtime_allowed": True,
        })
        sheet = self._sheet_for(today)
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "contract_id": contract.id,
            "overtime_hours": 2,
            "overtime_state": "submitted",
        })
        wizard = self.env["bambus.hr.overtime.wizard"].create({
            "line_id": line.id,
            "overtime_hours": 2,
            "calculation_type": "fixed_hour",
            "rate": 75,
        })

        self.assertEqual(wizard.overtime_amount, 150)
        wizard.action_save()
        self.assertEqual(line.overtime_state, "approved")
        self.assertEqual(line.overtime_calculation_type, "fixed_hour")
        self.assertEqual(line.overtime_amount, 150)

    def test_hr_user_can_save_overtime_without_approval_role(self):
        employee = self.env["hr.employee"].create({
            "name": "HR Update Employee",
            "company_id": self.env.company.id,
        })
        hr_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Attendance HR User",
            "login": "attendance.hr.user@example.test",
            "email": "attendance.hr.user@example.test",
            "groups_id": [(6, 0, [self.env.ref("hr.group_hr_user").id])],
        })
        today = fields.Date.context_today(employee)
        sheet = self._sheet_for(today)
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "overtime_hours": 1,
            "overtime_state": "submitted",
        })
        wizard = self.env["bambus.hr.overtime.wizard"].create({
            "line_id": line.id,
            "overtime_hours": 1,
            "calculation_type": "fixed_hour",
            "rate": 75,
        })

        wizard.with_user(hr_user).action_save()

        self.assertEqual(line.overtime_state, "approved")
        self.assertEqual(line.overtime_amount, 75)
        self.assertEqual(line.overtime_updated_by_id, hr_user)

    def test_hr_saves_regularized_zero_fine(self):
        employee = self.env["hr.employee"].create({
            "name": "Fine Approval Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        sheet = self._sheet_for(today)
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "fine_hours": 1,
            "fine_state": "submitted",
        })
        wizard = self.env["bambus.hr.fine.wizard"].create({
            "line_id": line.id,
            "fine_hours": 1,
            "calculation_type": "regularize",
        })

        self.assertEqual(wizard.fine_amount, 0)
        wizard.action_save()
        self.assertEqual(line.fine_state, "approved")
        dashboard = self.env["bambus.hr.attendance.sheet"].get_attendance_dashboard(
            fields.Date.to_string(today)
        )
        row = next(
            item for item in dashboard["daily_attendance"]
            if item["id"] == employee.id
        )
        fine_log = next(
            log for log in row["logs"]
            if log["type"] == "hr_update" and log["label"] == "Late / Fine adjusted"
        )
        self.assertEqual(fine_log["actor"], self.env.user.name)
        self.assertEqual(fine_log["details"], "01:00 hrs")
        self.assertEqual(line.fine_calculation_type, "regularize")
        self.assertEqual(line.fine_amount, 0)

    def test_fine_defaults_to_daily_salary_per_minute(self):
        day = fields.Date.to_date("2026-09-21")
        calendar = self.env["resource.calendar"].create({
            "name": "Fine Test 8 Hours",
            "tz": "UTC",
            "company_id": self.env.company.id,
            "attendance_ids": [(0, 0, {
                "name": "Monday",
                "dayofweek": "0",
                "day_period": "morning",
                "hour_from": 9.0,
                "hour_to": 17.0,
            })],
        })
        template = self.env["bambus.attendance.automation.template"].create({
            "name": "Salary Minute Fine",
            "company_id": self.env.company.id,
        })
        employee = self.env["hr.employee"].create({
            "name": "Salary Minute Employee",
            "company_id": self.env.company.id,
            "resource_calendar_id": calendar.id,
            "attendance_automation_template_id": template.id,
        })
        contract = self.env["hr.contract"].create({
            "name": "Salary Minute Contract",
            "employee_id": employee.id,
            "date_start": day,
            "resource_calendar_id": calendar.id,
            "wage": 12000,
            "wage_type": "monthly",
        })
        sheet = self._sheet_for(day)
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "contract_id": contract.id,
            "fine_hours": 10 / 60,
            "fine_state": "submitted",
        })
        wizard_model = self.env["bambus.hr.fine.wizard"].with_context(
            default_line_id=line.id
        )
        wizard = wizard_model.create(wizard_model.default_get([
            "line_id", "fine_hours", "detected_fine_hours",
            "calculation_type", "rate",
        ]))

        self.assertEqual(wizard.calculation_type, "salary_minute")
        self.assertAlmostEqual(wizard.salary_per_minute, 400 / 480, places=4)
        expected_amount = wizard.currency_id.round(10 * 400 / 480)
        self.assertEqual(wizard.fine_amount, expected_amount)
        wizard.action_save()
        self.assertEqual(line.fine_calculation_type, "salary_minute")
        self.assertAlmostEqual(line.fine_rate, 400 / 480, places=4)
        self.assertEqual(line.fine_amount, expected_amount)

    def test_full_day_leave_can_be_revoked(self):
        employee = self.env["hr.employee"].create({
            "name": "Full Day Leave Employee",
            "company_id": self.env.company.id,
        })
        leave_type = self._unpaid_leave_type(employee)
        today = fields.Date.context_today(employee)
        leave = self.env["hr.leave"].create({
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": today,
            "request_date_to": today,
            "name": "Full Day Leave",
        })
        self.env["bambus.hr.attendance.sheet"].revoke_dashboard_status(
            employee.id,
            fields.Date.to_string(today),
            "leave",
        )

        self.assertTrue(leave.exists())
        self.assertEqual(leave.state, "cancel")

    def test_attendance_list_shows_approved_daily_values_once(self):
        employee = self.env["hr.employee"].create({
            "name": "Approved Attendance List Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        start = datetime.combine(today, time(hour=9))
        attendance_model = self.env["hr.attendance"].with_context(
            bambus_skip_recompute=True, tz="UTC"
        )
        first = attendance_model.create({
            "employee_id": employee.id,
            "check_in": start,
            "check_out": start + timedelta(hours=4),
        })
        last = attendance_model.create({
            "employee_id": employee.id,
            "check_in": start + timedelta(hours=5),
            "check_out": start + timedelta(hours=9),
        })
        sheet = self._sheet_for(today)
        line = self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "overtime_hours": 1.5,
            "overtime_amount": 150,
            "overtime_state": "approved",
            "fine_hours": 0.25,
            "fine_amount": 12.5,
            "fine_state": "approved",
        })

        self.assertFalse(first.bambus_review_is_daily_summary)
        self.assertEqual(first.bambus_approved_overtime_hours, 0)
        self.assertEqual(first.bambus_approved_fine_hours, 0)
        self.assertTrue(last.bambus_review_is_daily_summary)
        self.assertEqual(last.bambus_review_line_id, line)
        self.assertEqual(last.bambus_overtime_review_state, "approved")
        self.assertEqual(last.bambus_approved_overtime_hours, 1.5)
        self.assertEqual(last.bambus_approved_overtime_amount, 150)
        self.assertEqual(last.bambus_fine_review_state, "approved")
        self.assertEqual(last.bambus_approved_fine_hours, 0.25)
        self.assertEqual(last.bambus_approved_fine_amount, 12.5)

        # Odoo form onchange uses a NewId record. It must not be sorted against
        # the persisted integer ID of the same attendance. Keep the same
        # checkout value so the computation cannot avoid the ID tie by sorting
        # on a different attendance time first.
        editing = last.new(last.copy_data()[0], origin=last)
        editing._compute_bambus_review_values()
        self.assertTrue(editing.bambus_review_is_daily_summary)
        self.assertEqual(editing.bambus_approved_overtime_hours, 1.5)
