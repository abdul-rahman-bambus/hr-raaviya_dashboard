from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestAttendanceAutomationEndToEnd(TransactionCase):
    """Exercise templates from attendance punches through HR update defaults."""

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
            overtime_rate_policy="fixed",
            overtime_rate=50,
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

    def _review_line(self, employee, contract, hours, day=None):
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
            "automation_template_id", "is_public_holiday", "salary_basis_amount",
            "overtime_slab_id", "rate_resolution_warning",
        ]
        return wizard_model.create(wizard_model.default_get(field_names))

    def _default_fine_wizard(self, line):
        wizard_model = self.env["bambus.hr.fine.wizard"].with_context(
            default_line_id=line.id
        )
        field_names = [
            "line_id", "detected_fine_hours", "fine_hours",
            "calculation_type", "rate", "salary_per_minute",
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
        self.assertAlmostEqual(attendance.bambus_fine_amount, 5 * 300 / 480, places=2)

    def test_open_punch_only_proposes_elapsed_late_time(self):
        template = self._create_template(
            "Open Punch Late Rule",
            late_grace_minutes=5,
            early_exit_enabled=True,
            break_enabled=True,
            allowed_break_minutes=0,
        )
        employee, _contract = self._create_employee_contract(
            "Open Punch Employee", template=template
        )
        attendance = self.env["hr.attendance"].with_context(
            bambus_skip_recompute=True
        ).create({
            "employee_id": employee.id,
            "check_in": datetime.combine(
                self.test_day, datetime.min.time()
            ).replace(hour=9, minute=10),
        })

        self.env["hr.attendance.overtime"].bambus_recompute_range(
            employee.ids, self.test_day, self.test_day
        )
        attendance.invalidate_recordset()

        self.assertEqual(attendance.bambus_late_minutes, 5)
        self.assertEqual(attendance.bambus_early_leave_minutes, 0)
        self.assertEqual(attendance.bambus_gap_minutes, 0)
        self.assertAlmostEqual(attendance.bambus_fine_hours, 5 / 60, places=4)

    def test_post_lunch_late_uses_separate_zero_grace(self):
        split_calendar = self.env["resource.calendar"].create({
            "name": "Split Shift 09:00-14:00 and 14:45-17:00",
            "tz": "UTC",
            "company_id": self.company.id,
            "attendance_ids": [
                (0, 0, {
                    "name": "Monday Morning",
                    "dayofweek": "0",
                    "day_period": "morning",
                    "hour_from": 9.0,
                    "hour_to": 14.0,
                }),
                (0, 0, {
                    "name": "Monday Afternoon",
                    "dayofweek": "0",
                    "day_period": "afternoon",
                    "hour_from": 14.75,
                    "hour_to": 17.0,
                }),
            ],
        })
        template = self._create_template(
            "Separate Post-Break Grace",
            late_grace_minutes=5,
            post_break_grace_minutes=0,
            break_enabled=True,
            allowed_break_minutes=45,
        )
        employee, contract = self._create_employee_contract(
            "Post-Lunch Late Employee", template=template
        )
        employee.resource_calendar_id = split_calendar
        contract.resource_calendar_id = split_calendar
        attendance_model = self.env["hr.attendance"].with_context(
            bambus_skip_recompute=True
        )
        attendance_model.create({
            "employee_id": employee.id,
            "check_in": datetime(2026, 9, 21, 9, 4),
            "check_out": datetime(2026, 9, 21, 14, 0),
        })
        afternoon = attendance_model.create({
            "employee_id": employee.id,
            "check_in": datetime(2026, 9, 21, 14, 46),
            "check_out": datetime(2026, 9, 21, 17, 0),
        })

        self.env["hr.attendance.overtime"].bambus_recompute_range(
            employee.ids, self.test_day, self.test_day
        )
        afternoon.invalidate_recordset()

        self.assertEqual(afternoon.bambus_late_minutes, 1)
        self.assertAlmostEqual(afternoon.bambus_fine_hours, 1 / 60, places=4)

    def test_dashboard_review_opens_detected_values_and_saves_snapshots(self):
        employee, contract = self._create_employee_contract(
            "Direct Dashboard Review", wage=10000
        )
        self._create_attendance(employee, (9, 10), (18, 10))
        sheet_model = self.env["bambus.hr.attendance.sheet"]

        overtime_action = sheet_model.open_dashboard_adjustment(
            employee.id, fields.Date.to_string(self.test_day), "overtime"
        )
        line = self.env["bambus.hr.attendance.sheet.line"].browse(
            overtime_action["context"]["default_line_id"]
        )
        self.assertEqual(overtime_action["res_model"], "bambus.hr.overtime.wizard")
        self.assertAlmostEqual(line.overtime_hours, 70 / 60, places=4)
        self.assertAlmostEqual(line.fine_hours, 5 / 60, places=4)

        overtime_wizard = self._default_overtime_wizard(line)
        self.assertAlmostEqual(
            overtime_wizard.detected_overtime_hours, 70 / 60, places=4
        )
        self.assertEqual(overtime_wizard.rate, self.company_template.overtime_rate)
        overtime_wizard.action_save()
        self.assertEqual(line.overtime_state, "approved")
        self.assertAlmostEqual(line.overtime_amount, 70 / 60 * 50, places=2)

        fine_action = sheet_model.open_dashboard_adjustment(
            employee.id, fields.Date.to_string(self.test_day), "fine"
        )
        self.assertEqual(fine_action["res_model"], "bambus.hr.fine.wizard")
        self.assertEqual(fine_action["context"]["default_line_id"], line.id)
        fine_model = self.env["bambus.hr.fine.wizard"].with_context(
            default_line_id=line.id
        )
        fine_wizard = fine_model.create(fine_model.default_get([
            "line_id", "detected_fine_hours", "fine_hours",
            "calculation_type", "rate",
        ]))
        self.assertEqual(fine_wizard.calculation_type, "salary_minute")
        self.assertAlmostEqual(fine_wizard.detected_fine_hours, 5 / 60, places=4)
        expected_fine = fine_wizard.currency_id.round(5 * (10000 / 30) / 480)
        self.assertEqual(fine_wizard.fine_amount, expected_fine)
        fine_wizard.action_save()
        self.assertEqual(line.fine_state, "approved")
        self.assertEqual(line.fine_amount, expected_fine)

    def test_assigned_template_drives_ot_and_fine_without_legacy_switches(self):
        self.company.bambus_ot_mode = "odoo"
        template = self._create_template(
            "Template Driven Detection",
            late_grace_minutes=5,
            minimum_overtime_minutes=0,
            overtime_start_mode="fixed",
            overtime_start_hour=17.0,
            overtime_end_mode="fixed",
            overtime_end_hour=18.0,
            fine_calculation_type="salary_minute",
        )
        employee, contract = self._create_employee_contract(
            "Template Driven Employee", wage=9000, template=template
        )
        contract.write({
            "is_overtime_allowed": False,
            "is_latefine_applicable": False,
        })

        attendance = self._create_attendance(employee, (9, 10), (17, 30))

        self.assertAlmostEqual(self._base_overtime(employee).duration, 0.5, places=4)
        self.assertEqual(attendance.bambus_late_minutes, 5)
        self.assertAlmostEqual(attendance.bambus_fine_hours, 5 / 60, places=4)
        self.assertAlmostEqual(attendance.bambus_fine_amount, 5 * 300 / 480, places=2)

    def test_disabled_template_ignores_enabled_legacy_contract_switches(self):
        template = self._create_template(
            "Disabled Template Is Authoritative",
            overtime_enabled=False,
            late_enabled=False,
            early_exit_enabled=False,
            break_enabled=False,
        )
        employee, contract = self._create_employee_contract(
            "Legacy Switch Employee", template=template
        )
        contract.write({
            "is_overtime_allowed": True,
            "is_latefine_applicable": True,
            "apply_late_fine": "fixed",
            "late_fine_rate": 99,
        })

        attendance = self._create_attendance(employee, (9, 10), (18, 10))

        self.assertFalse(self._base_overtime(employee).duration)
        self.assertFalse(attendance.bambus_fine_hours)
        self.assertFalse(attendance.bambus_fine_amount)

    def test_salary_rules_use_approved_automation_snapshots(self):
        category = self.env["hr.salary.rule.category"].search([], limit=1)
        self.assertTrue(category)
        rules = self.env["hr.salary.rule"].create([{
            "name": name,
            "code": code,
            "category_id": category.id,
            "condition_select": "none",
            "amount_select": "code",
            "amount_python_compute": "result = contract.overtime_rate",
        } for code, name in (
            ("OT", "Automation OT Test"),
            ("LATE", "Automation Fine Test"),
            ("PH", "Legacy Public Holiday Test"),
        )])

        rules._bambus_use_automation_amounts()

        self.assertEqual(
            rules.filtered(lambda rule: rule.code == "OT").amount_python_compute,
            "result = payslip.total_overtime_amount or 0.0",
        )
        self.assertEqual(
            rules.filtered(lambda rule: rule.code == "LATE").amount_python_compute,
            "result = -(payslip.total_fine_amount or 0.0)",
        )
        self.assertEqual(
            rules.filtered(lambda rule: rule.code == "PH").amount_python_compute,
            "result = 0.0",
        )

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

    def test_fixed_overtime_window_uses_exact_minutes_and_caps_at_end(self):
        window_template = self._create_template(
            "Configurable OT Window",
            minimum_overtime_minutes=0,
            overtime_start_mode="fixed",
            overtime_start_hour=17.25,
            overtime_end_mode="fixed",
            overtime_end_hour=18.0,
            overtime_rounding_minutes="0",
        )
        before, _contract = self._create_employee_contract(
            "Before Window Employee", template=window_template
        )
        inside, _contract = self._create_employee_contract(
            "Inside Window Employee", template=window_template
        )
        capped, _contract = self._create_employee_contract(
            "Capped Window Employee", template=window_template
        )

        self._create_attendance(before, (9, 0), (17, 15))
        self._create_attendance(inside, (9, 0), (17, 30))
        self._create_attendance(capped, (9, 0), (18, 30))

        self.assertFalse(self._base_overtime(before).duration)
        self.assertAlmostEqual(self._base_overtime(inside).duration, 0.25, places=4)
        self.assertAlmostEqual(self._base_overtime(capped).duration, 0.75, places=4)

    def test_weekly_off_policy_proposes_all_worked_hours(self):
        template = self._create_template(
            "Weekly Off Work",
            weekly_off_overtime_policy="all",
            minimum_overtime_minutes=0,
        )
        employee, _contract = self._create_employee_contract(
            "Weekly Off Employee", template=template
        )
        sunday = self.test_day + timedelta(days=6)

        self._create_attendance(employee, (9, 0), (15, 0), day=sunday)

        self.assertEqual(self._base_overtime(employee, sunday).duration, 6.0)

    def test_weekly_off_policy_ignores_legacy_contract_switch(self):
        template = self._create_template(
            "Weekly Off Disabled",
            weekly_off_overtime_policy="disabled",
            minimum_overtime_minutes=0,
        )
        employee, contract = self._create_employee_contract(
            "Legacy Weekend Employee", template=template
        )
        contract.write({
            "weekend_special_working": True,
            "weekend_wage_type": "fixed",
            "weekend_wage_rate": 500,
        })
        sunday = self.test_day + timedelta(days=6)

        self._create_attendance(employee, (9, 0), (15, 0), day=sunday)

        self.assertFalse(self._base_overtime(employee, sunday).duration)

    def test_public_holiday_policy_proposes_all_worked_hours(self):
        template = self._create_template(
            "Public Holiday Work",
            public_holiday_overtime_policy="all",
            minimum_overtime_minutes=0,
        )
        employee, contract = self._create_employee_contract(
            "Public Holiday Employee", template=template
        )
        self.env["resource.calendar.leaves"].create({
            "name": "Automation Test Holiday",
            "calendar_id": self.calendar.id,
            "date_from": datetime.combine(self.test_day, datetime.min.time()),
            "date_to": datetime.combine(
                self.test_day + timedelta(days=1), datetime.min.time()
            ),
        })

        self._create_attendance(employee, (9, 0), (15, 0))

        self.assertEqual(self._base_overtime(employee).duration, 6.0)
        payroll_holidays = self.env["hr.payslip"]._get_public_holiday_dates(
            contract, self.test_day, self.test_day, "UTC"
        )
        self.assertIn(self.test_day, payroll_holidays)

    def test_public_holiday_policy_defaults_to_all_worked_hours(self):
        template = self._create_template("Default Public Holiday Policy")

        self.assertEqual(template.public_holiday_overtime_policy, "all")
        self.assertEqual(template.public_holiday_calculation_type, "salary_2")
        self.assertEqual(template.public_holiday_rate_policy, "salary_multiplier")

    def test_public_holiday_disabled_policy_does_not_propose_overtime(self):
        template = self._create_template(
            "No Public Holiday Overtime",
            public_holiday_overtime_policy="disabled",
            minimum_overtime_minutes=0,
        )
        employee, _contract = self._create_employee_contract(
            "No Holiday OT Employee", template=template
        )
        self.env["resource.calendar.leaves"].create({
            "name": "No OT Holiday",
            "calendar_id": False,
            "resource_id": False,
            "date_from": datetime.combine(self.test_day, datetime.min.time()),
            "date_to": datetime.combine(
                self.test_day + timedelta(days=1), datetime.min.time()
            ),
        })

        self._create_attendance(employee, (9, 0), (15, 0))

        self.assertFalse(self._base_overtime(employee).duration)

    def test_global_public_holiday_applies_without_work_schedule(self):
        template = self._create_template(
            "Global Public Holiday Work",
            public_holiday_overtime_policy="all",
            public_holiday_calculation_type="fixed_hour",
            public_holiday_rate_policy="fixed",
            public_holiday_rate=125,
            minimum_overtime_minutes=0,
        )
        employee, contract = self._create_employee_contract(
            "Global Holiday Employee", template=template
        )
        contract.resource_calendar_id = False
        employee.resource_calendar_id = False
        self.env["resource.calendar.leaves"].create({
            "name": "All Companies Holiday",
            "calendar_id": False,
            "resource_id": False,
            "date_from": datetime.combine(self.test_day, datetime.min.time()),
            "date_to": datetime.combine(
                self.test_day + timedelta(days=1), datetime.min.time()
            ),
        })

        self._create_attendance(employee, (9, 0), (15, 0))

        self.assertEqual(self._base_overtime(employee).duration, 6.0)
        payroll_holidays = self.env["hr.payslip"]._get_public_holiday_dates(
            contract, self.test_day, self.test_day, "UTC"
        )
        self.assertIn(self.test_day, payroll_holidays)
        line = self._review_line(employee, contract, 6.0)
        wizard = self._default_overtime_wizard(line)
        self.assertTrue(wizard.is_public_holiday)
        self.assertEqual(wizard.calculation_type, "fixed_hour")
        self.assertEqual(wizard.rate, 125)
        self.assertEqual(wizard.overtime_amount, 750)
        wizard.action_save()
        self.assertEqual(line.overtime_rate, 125)
        self.assertEqual(line.overtime_amount, 750)

    def test_hourly_worker_payslip_counts_global_public_holiday(self):
        employee, contract = self._create_employee_contract(
            "Hourly Holiday Employee", template=self.company_template
        )
        employee.employee_type = "worker"
        employee.resource_calendar_id = False
        contract.write({
            "wage_type": "hourly",
            "hourly_rate": 25,
            "resource_calendar_id": False,
        })
        self.env["resource.calendar.leaves"].create({
            "name": "Hourly Global Holiday",
            "calendar_id": False,
            "resource_id": False,
            "date_from": datetime.combine(self.test_day, datetime.min.time()),
            "date_to": datetime.combine(
                self.test_day + timedelta(days=1), datetime.min.time()
            ),
        })
        payslip = self.env["hr.payslip"].create({
            "name": "Hourly Holiday Payslip",
            "employee_id": employee.id,
            "contract_id": contract.id,
            "date_from": self.test_day,
            "date_to": self.test_day,
        })

        payslip._compute_all_stats()

        self.assertEqual(payslip.holiday_days, 1.0)
        self.assertEqual(payslip.days_excl_weekend_holidays, 0.0)

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

    def test_salary_slabs_drive_saved_update_after_detection(self):
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

                line = self._review_line(employee, contract, 1)
                wizard = self._default_overtime_wizard(line)
                self.assertEqual(wizard.automation_template_id, slab_template)
                self.assertEqual(wizard.calculation_type, "fixed_hour")
                self.assertEqual(wizard.salary_basis_amount, wage)
                self.assertEqual(wizard.rate, expected_rate)
                self.assertEqual(wizard.overtime_amount, expected_rate)
                wizard.action_save()
                self.assertEqual(line.overtime_state, "approved")
                self.assertEqual(line.overtime_amount, expected_rate)

    def test_salary_change_keeps_saved_snapshot(self):
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
        first_line = self._review_line(employee, contract, 1)
        first_wizard = self._default_overtime_wizard(first_line)
        first_wizard.action_save()

        contract.wage = 13000
        second_line = self._review_line(
            employee, contract, 1, day=self.test_day + timedelta(days=1)
        )
        second_wizard = self._default_overtime_wizard(second_line)

        self.assertEqual(first_line.overtime_salary_basis_amount, 9000)
        self.assertEqual(first_line.overtime_rate, 75)
        self.assertEqual(first_line.overtime_amount, 75)
        self.assertEqual(second_wizard.salary_basis_amount, 13000)
        self.assertEqual(second_wizard.rate, 120)
        self.assertEqual(second_wizard.overtime_amount, 120)

    def test_every_overtime_calculation_option(self):
        """Every calculation choice shown to HR produces a known amount."""
        employee, contract = self._create_employee_contract(
            "OT Calculation Matrix", wage=12000
        )
        line = self._review_line(employee, contract, 2)
        expected = {
            "fixed": 80,
            "fixed_hour": 160,
            "half_day": 200,
            "full_day": 400,
            "regularize": 0,
            "salary_1": 100,
            "salary_1_5": 150,
            "salary_2": 200,
        }
        for calculation_type, expected_amount in expected.items():
            with self.subTest(calculation_type=calculation_type):
                wizard = self._default_overtime_wizard(line)
                wizard.write({
                    "overtime_hours": 2,
                    "calculation_type": calculation_type,
                    "rate": 80,
                })
                self.assertAlmostEqual(wizard.overtime_amount, expected_amount, places=2)

    def test_every_public_holiday_calculation_option_saves_snapshot(self):
        """Every holiday calculation default reaches the approved sheet snapshot."""
        self.env["resource.calendar.leaves"].create({
            "name": "Holiday Calculation Matrix",
            "calendar_id": False,
            "resource_id": False,
            "date_from": datetime.combine(self.test_day, datetime.min.time()),
            "date_to": datetime.combine(
                self.test_day + timedelta(days=1), datetime.min.time()
            ),
        })
        expected = {
            "fixed": 80,
            "fixed_hour": 160,
            "half_day": 200,
            "full_day": 400,
            "regularize": 0,
            "salary_1": 100,
            "salary_1_5": 150,
            "salary_2": 200,
        }
        for calculation_type, expected_amount in expected.items():
            with self.subTest(calculation_type=calculation_type):
                template = self._create_template(
                    "Holiday Calculation %s" % calculation_type,
                    public_holiday_calculation_type=calculation_type,
                    public_holiday_rate_policy="fixed",
                    public_holiday_rate=80,
                )
                employee, contract = self._create_employee_contract(
                    "Holiday %s Employee" % calculation_type,
                    wage=12000,
                    template=template,
                )
                line = self._review_line(employee, contract, 2)
                wizard = self._default_overtime_wizard(line)

                self.assertTrue(wizard.is_public_holiday)
                self.assertEqual(wizard.calculation_type, calculation_type)
                self.assertEqual(wizard.rate, 80)
                self.assertAlmostEqual(
                    wizard.overtime_amount, expected_amount, places=2
                )
                wizard.action_save()
                self.assertEqual(line.overtime_calculation_type, calculation_type)
                self.assertEqual(line.overtime_rate, 80)
                self.assertAlmostEqual(line.overtime_amount, expected_amount, places=2)

    def test_every_fine_calculation_option(self):
        """Fine choices include salary-per-minute as the safe default."""
        employee, contract = self._create_employee_contract(
            "Fine Calculation Matrix", wage=12000
        )
        line = self._review_line(employee, contract, 0)
        line.write({"fine_hours": 2, "fine_detected_hours": 2})
        expected = {
            "fixed": 80,
            "fixed_hour": 160,
            "half_day": 200,
            "full_day": 400,
            "regularize": 0,
            "salary_minute": 100,
            "salary_1": 100,
            "salary_1_5": 150,
            "salary_2": 200,
        }
        for calculation_type, expected_amount in expected.items():
            with self.subTest(calculation_type=calculation_type):
                wizard = self._default_fine_wizard(line)
                wizard.write({
                    "fine_hours": 2,
                    "calculation_type": calculation_type,
                    "rate": 80,
                })
                self.assertAlmostEqual(wizard.fine_amount, expected_amount, places=2)

    def test_every_overtime_rounding_option(self):
        engine = self.env["hr.attendance.overtime"]
        expected = {"0": 44, "15": 30, "30": 30, "60": 0}
        for rounding, expected_minutes in expected.items():
            with self.subTest(rounding=rounding):
                template = self._create_template(
                    "Rounding %s" % rounding,
                    overtime_rounding_minutes=rounding,
                )
                self.assertEqual(
                    engine._round_overtime_minutes(44, template),
                    expected_minutes,
                )

    def test_fixed_multiplier_and_slab_rate_policies(self):
        employee, contract = self._create_employee_contract(
            "Rate Policy Matrix", wage=10000
        )
        fixed = self._create_template(
            "Fixed Rate Policy", overtime_rate_policy="fixed", overtime_rate=90
        )
        multiplier = self._create_template(
            "Salary Multiplier Policy", overtime_rate_policy="salary_multiplier"
        )
        slab = self._create_template(
            "Slab Rate Policy",
            overtime_rate_policy="salary_slab",
            overtime_slab_ids=[
                (0, 0, {"salary_from": 0, "salary_to": 12000, "rate": 110}),
            ],
        )
        self.assertEqual(fixed.resolve_overtime_rate(contract)[0], 90)
        self.assertEqual(multiplier.resolve_overtime_rate(contract)[0], 0)
        self.assertEqual(slab.resolve_overtime_rate(contract)[0], 110)

    def test_every_public_holiday_rate_policy(self):
        _employee, contract = self._create_employee_contract(
            "Holiday Rate Policy Matrix", wage=10000
        )
        fixed = self._create_template(
            "Holiday Fixed Rate",
            public_holiday_rate_policy="fixed",
            public_holiday_rate=95,
        )
        multiplier = self._create_template(
            "Holiday Salary Multiplier",
            public_holiday_rate_policy="salary_multiplier",
        )
        slab = self._create_template(
            "Holiday Slab Rate",
            public_holiday_rate_policy="salary_slab",
            overtime_slab_ids=[
                (0, 0, {"salary_from": 0, "salary_to": 12000, "rate": 115}),
            ],
        )

        self.assertEqual(fixed.resolve_public_holiday_rate(contract)[0], 95)
        self.assertEqual(multiplier.resolve_public_holiday_rate(contract)[0], 0)
        self.assertEqual(slab.resolve_public_holiday_rate(contract)[0], 115)
