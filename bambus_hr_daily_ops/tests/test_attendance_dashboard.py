from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestAttendanceDashboard(TransactionCase):

    def test_overtime_salary_slabs_resolve_contract_wage_boundaries(self):
        template = self.env["bambus.attendance.automation.template"].create({
            "name": "Salary Slab Rules",
            "company_id": self.env.company.id,
            "overtime_rate_policy": "salary_slab",
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
        sheet = self.env["bambus.hr.attendance.sheet"].create({
            "date": fields.Date.context_today(employee),
            "company_id": self.env.company.id,
        })
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
        wizard.action_approve()
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

    def test_manager_confirms_overtime_calculation_before_approval(self):
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
        sheet = self.env["bambus.hr.attendance.sheet"].create({
            "date": today,
            "company_id": self.env.company.id,
        })
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
        wizard.action_approve()
        self.assertEqual(line.overtime_state, "approved")
        self.assertEqual(line.overtime_calculation_type, "fixed_hour")
        self.assertEqual(line.overtime_amount, 150)

    def test_regularized_fine_approves_zero_deduction(self):
        employee = self.env["hr.employee"].create({
            "name": "Fine Approval Employee",
            "company_id": self.env.company.id,
        })
        today = fields.Date.context_today(employee)
        sheet = self.env["bambus.hr.attendance.sheet"].create({
            "date": today,
            "company_id": self.env.company.id,
        })
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
        wizard.action_approve()
        self.assertEqual(line.fine_state, "approved")
        self.assertEqual(line.fine_calculation_type, "regularize")
        self.assertEqual(line.fine_amount, 0)

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

        self.assertTrue(leave.exists())
        self.assertEqual(leave.state, "cancel")
