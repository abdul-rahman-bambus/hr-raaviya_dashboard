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
