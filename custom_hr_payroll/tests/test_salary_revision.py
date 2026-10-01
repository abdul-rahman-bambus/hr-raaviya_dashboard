from datetime import date

from odoo.tests.common import TransactionCase


class TestSalaryRevision(TransactionCase):

    def test_employee_number_is_generated_on_create(self):
        employee = self.env["hr.employee"].create({"name": "Sequenced Employee"})

        self.assertTrue(employee.employee_number.startswith("EMP/"))

    def test_draft_monthly_payslip_revision_updates_contract_and_history(self):
        employee = self.env["hr.employee"].create({"name": "Revised Employee"})
        contract = self.env["hr.contract"].create({
            "name": "Monthly Contract",
            "employee_id": employee.id,
            "date_start": date(2026, 10, 1),
            "wage_type": "monthly",
            "wage": 18000,
        })
        payslip = self.env["hr.payslip"].create({
            "name": "October Salary",
            "employee_id": employee.id,
            "contract_id": contract.id,
            "date_from": date(2026, 10, 1),
            "date_to": date(2026, 10, 31),
        })
        wizard_model = self.env["hr.salary.revision.wizard"].with_context(
            default_payslip_id=payslip.id
        )
        defaults = wizard_model.default_get([
            "payslip_id", "current_wage", "revised_wage", "effective_date",
        ])
        wizard = wizard_model.create({
            **defaults,
            "revised_wage": 21000,
            "reason": "Annual revision",
        })

        wizard.action_apply_revision()

        revision = contract.salary_revision_ids
        self.assertEqual(contract.wage, 21000)
        self.assertEqual(len(revision), 1)
        self.assertEqual(revision.previous_wage, 18000)
        self.assertEqual(revision.revised_wage, 21000)
        self.assertEqual(revision.difference, 3000)
        self.assertAlmostEqual(revision.percentage_change, 1 / 6)
        self.assertEqual(revision.payslip_id, payslip)

    def test_hourly_to_monthly_revision_creates_new_contract(self):
        employee = self.env["hr.employee"].create({"name": "Converted Employee"})
        calendar = self.env["resource.calendar"].create({"name": "Monthly Shift"})
        hourly_contract = self.env["hr.contract"].create({
            "name": "Hourly Contract",
            "employee_id": employee.id,
            "date_start": date(2026, 9, 1),
            "wage_type": "hourly",
            "hourly_rate": 25,
            "wage": 0,
        })
        payslip = self.env["hr.payslip"].create({
            "name": "November Salary",
            "employee_id": employee.id,
            "contract_id": hourly_contract.id,
            "date_from": date(2026, 11, 1),
            "date_to": date(2026, 11, 30),
        })
        wizard = self.env["hr.salary.revision.wizard"].create({
            "payslip_id": payslip.id,
            "current_wage": 25,
            "revised_wage_type": "monthly",
            "revised_wage": 18000,
            "revised_calendar_id": calendar.id,
            "effective_date": payslip.date_from,
            "reason": "Promoted to monthly staff",
        })

        wizard.action_apply_revision()

        revised_contract = payslip.contract_id
        self.assertNotEqual(revised_contract, hourly_contract)
        self.assertEqual(hourly_contract.date_end, date(2026, 10, 31))
        self.assertEqual(revised_contract.date_start, date(2026, 11, 1))
        self.assertEqual(revised_contract.wage_type, "monthly")
        self.assertEqual(revised_contract.wage, 18000)
        self.assertEqual(revised_contract.resource_calendar_id, calendar)
        self.assertEqual(revised_contract.salary_revision_ids.previous_wage_type, "hourly")
