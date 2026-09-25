from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestAttendanceAutomationEndToEnd(TransactionCase):
    """Exercise templates from attendance punches through HR approval defaults."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_day = fields.Date.to_date("2026-09-21")  # Monday
        cls.company = cls.env.company
        cls.company.bambus_ot_mode = "custom"
        if "overtime_company_threshold" in cls.company._fields:
            cls.company.overtime_company_threshold = 0

        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Automation Test 09:00-17:00",
            "tz": "UTC",
            "company_id": cls.company.id,
            "attendance_ids": [(0, 0, {
                "name": "Monday",
                "dayofweek": "0",
                "day_period": "morning",
                "hour_from": 9.0,
                "hour_to": 17.0,
            })],
        })
        cls.company_template = cls._create_template(
            "Company Automation",
            late_grace_minutes=5,
            early_exit_grace_minutes=5,
            minimum_overtime_minutes=60,
        )
        cls.company.attendance_automation_template_id = cls.company_template

    @classmethod
    def _create_template(cls, name, **values):
        values.update({"name": name, "company_id": cls.company.id})
        return cls.env["bambus.attendance.automation.template"].create(values)

    @classmethod
    def _create_employee_contract(cls, name, wage=9000, template=None):
        employee = cls.env["hr.employee"].create({
            "name": name,
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
            "attendance_automation_template_id": template.id if template else False,
        })
        contract = cls.env["hr.contract"].create({
            "name": f"{name} Contract",
            "employee_id": employee.id,
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
            "date_start": cls.test_day - timedelta(days=30),
            "wage": wage,
            "wage_type": "monthly",
            "is_overtime_allowed": True,
            "overtime_rate": 50,
            "is_latefine_applicable": True,
            "apply_late_fine": "fixed",
            "late_fine_rate": 2,
        })
        return employee, contract

    def _create_attendance(self, employee, check_in, check_out, day=None):
        day = day or self.test_day
        attendance = self.env["hr.attendance"].with_context(
            bambus_skip_recompute=True
        ).create({
            "employee_id": employee.id,
            "check_in": datetime.combine(day, datetime.min.time()).replace(
                hour=check_in[0], minute=check_in[1]
            ),
            "check_out": datetime.combine(day, datetime.min.time()).replace(
                hour=check_out[0], minute=check_out[1]
            ),
        })
        self.env["hr.attendance.overtime"].bambus_recompute_range(
            employee.ids, day, day
        )
        attendance.invalidate_recordset()
        return attendance

    def _base_overtime(self, employee, day=None):
        return self.env["hr.attendance.overtime"].search([
            ("employee_id", "=", employee.id),
            ("date", "=", day or self.test_day),
            ("adjustment", "=", False),
        ], limit=1)

    def _approval_line(self, employee, contract, hours, day=None):
        day = day or self.test_day
        sheet = self.env["bambus.hr.attendance.sheet"].search([
            ("date", "=", day),
            ("company_id", "=", self.company.id),
        ], limit=1) or self.env["bambus.hr.attendance.sheet"].create({
            "date": day,
            "company_id": self.company.id,
        })
        return self.env["bambus.hr.attendance.sheet.line"].create({
            "sheet_id": sheet.id,
            "employee_id": employee.id,
            "contract_id": contract.id,
            "overtime_hours": hours,
            "overtime_state": "submitted",
        })

    def _default_overtime_wizard(self, line):
        wizard_model = self.env["bambus.hr.overtime.wizard"].with_context(
            default_line_id=line.id
        )
        field_names = [
            "line_id", "detected_overtime_hours", "overtime_hours",
            "calculation_type", "rate", "resolved_rate",
            "automation_template_id", "salary_basis_amount",
            "overtime_slab_id", "rate_resolution_warning",
        ]
        return wizard_model.create(wizard_model.default_get(field_names))

    def test_company_default_calculates_overtime_late_and_fine(self):
        employee, _contract = self._create_employee_contract("Company Rule Employee")

        attendance = self._create_attendance(employee, (9, 10), (18, 10))

        self.assertEqual(
            employee._get_attendance_automation_template(self.test_day),
            self.company_template,
        )
        self.assertAlmostEqual(self._base_overtime(employee).duration, 70 / 60, places=4)
        self.assertEqual(attendance.bambus_late_minutes, 5)
        self.assertAlmostEqual(attendance.bambus_fine_hours, 5 / 60, places=4)
        self.assertEqual(attendance.bambus_fine_amount, 10)

    def test_minimum_overtime_is_inclusive_at_sixty_minutes(self):
        below_employee, _contract = self._create_employee_contract("59 Minute Employee")
        exact_employee, _contract = self._create_employee_contract("60 Minute Employee")

        self._create_attendance(below_employee, (9, 0), (17, 59))
        self._create_attendance(exact_employee, (9, 0), (18, 0))

        self.assertFalse(self._base_overtime(below_employee).duration)
        self.assertEqual(self._base_overtime(exact_employee).duration, 1.0)

    def test_employee_template_overrides_company_detection_rules(self):
        employee_template = self._create_template(
            "Employee 30 Minute Automation",
            late_grace_minutes=0,
            minimum_overtime_minutes=30,
        )
        employee, _contract = self._create_employee_contract(
            "Employee Override", template=employee_template
        )

        attendance = self._create_attendance(employee, (9, 10), (17, 45))

        self.assertEqual(
            employee._get_attendance_automation_template(self.test_day),
            employee_template,
        )
        self.assertAlmostEqual(self._base_overtime(employee).duration, 0.75, places=4)
        self.assertEqual(attendance.bambus_late_minutes, 10)

    def test_expired_employee_template_falls_back_to_company_default(self):
        expired_template = self._create_template(
            "Expired Employee Automation",
            date_to=self.test_day - timedelta(days=1),
            minimum_overtime_minutes=15,
        )
        employee, _contract = self._create_employee_contract(
            "Expired Template Employee", template=expired_template
        )

        self._create_attendance(employee, (9, 0), (17, 45))

        self.assertEqual(
            employee._get_attendance_automation_template(self.test_day),
            self.company_template,
        )
        self.assertFalse(self._base_overtime(employee).duration)

    def test_disabled_rules_clear_overtime_and_late_fine(self):
        disabled_template = self._create_template(
            "Disabled Automation",
            late_enabled=False,
            early_exit_enabled=False,
            break_enabled=False,
            overtime_enabled=False,
        )
        employee, _contract = self._create_employee_contract(
            "Disabled Rule Employee", template=disabled_template
        )

        attendance = self._create_attendance(employee, (9, 30), (18, 30))

        self.assertFalse(self._base_overtime(employee).duration)
        self.assertEqual(attendance.bambus_late_minutes, 0)
        self.assertEqual(attendance.bambus_fine_hours, 0)
        self.assertEqual(attendance.bambus_fine_amount, 0)

    def test_salary_slabs_drive_approval_after_attendance_detection(self):
        slab_template = self._create_template(
            "Salary Slab Automation",
            minimum_overtime_minutes=60,
            overtime_calculation_type="fixed_hour",
            overtime_rate_policy="salary_slab",
            overtime_salary_basis="monthly",
            overtime_slab_ids=[
                (0, 0, {"salary_from": 0, "salary_to": 9000, "rate": 75}),
                (0, 0, {"salary_from": 9000.01, "salary_to": 12000, "rate": 100}),
                (0, 0, {"salary_from": 12000.01, "has_maximum": False, "rate": 120}),
            ],
        )
        scenarios = [
            ("Lower Slab Employee", 9000, 75),
            ("Middle Slab Employee", 10000, 100),
            ("Open Slab Employee", 13000, 120),
        ]

        for name, wage, expected_rate in scenarios:
            with self.subTest(wage=wage, expected_rate=expected_rate):
                employee, contract = self._create_employee_contract(
                    name, wage=wage, template=slab_template
                )
                self._create_attendance(employee, (9, 0), (18, 0))
                self.assertEqual(self._base_overtime(employee).duration, 1.0)

                line = self._approval_line(employee, contract, 1)
                wizard = self._default_overtime_wizard(line)
                self.assertEqual(wizard.automation_template_id, slab_template)
                self.assertEqual(wizard.salary_basis_amount, wage)
                self.assertEqual(wizard.rate, expected_rate)
                self.assertEqual(wizard.overtime_amount, expected_rate)
                wizard.action_approve()
                self.assertEqual(line.overtime_state, "approved")
                self.assertEqual(line.overtime_amount, expected_rate)

    def test_salary_change_updates_new_rate_but_not_approved_snapshot(self):
        slab_template = self._create_template(
            "Salary Change Automation",
            overtime_calculation_type="fixed_hour",
            overtime_rate_policy="salary_slab",
            overtime_salary_basis="monthly",
            overtime_slab_ids=[
                (0, 0, {"salary_from": 0, "salary_to": 9000, "rate": 75}),
                (0, 0, {"salary_from": 9000.01, "salary_to": 12000, "rate": 100}),
                (0, 0, {"salary_from": 12000.01, "has_maximum": False, "rate": 120}),
            ],
        )
        employee, contract = self._create_employee_contract(
            "Salary Change Employee", wage=9000, template=slab_template
        )
        first_line = self._approval_line(employee, contract, 1)
        first_wizard = self._default_overtime_wizard(first_line)
        first_wizard.action_approve()

        contract.wage = 13000
        second_line = self._approval_line(
            employee, contract, 1, day=self.test_day + timedelta(days=1)
        )
        second_wizard = self._default_overtime_wizard(second_line)

        self.assertEqual(first_line.overtime_salary_basis_amount, 9000)
        self.assertEqual(first_line.overtime_rate, 75)
        self.assertEqual(first_line.overtime_amount, 75)
        self.assertEqual(second_wizard.salary_basis_amount, 13000)
        self.assertEqual(second_wizard.rate, 120)
        self.assertEqual(second_wizard.overtime_amount, 120)
