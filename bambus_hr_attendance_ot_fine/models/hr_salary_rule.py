from odoo import api, models


class HrSalaryRule(models.Model):
    _inherit = "hr.salary.rule"

    @api.model
    def _bambus_use_automation_amounts(self):
        """Move attendance adjustments to the approved template snapshots.

        Regular overtime and public-holiday work have separate payslip totals so
        each earning is visible under its matching salary rule without being
        paid twice.
        """
        net_rules = self.search([("code", "=", "NET")])
        deductions_are_positive = any(
            "-categories.DED" in "".join(
                (rule.amount_python_compute or "").split()
            )
            for rule in net_rules
        )
        fine_expression = (
            "result = payslip.total_fine_amount or 0.0"
            if deductions_are_positive
            else "result = -(payslip.total_fine_amount or 0.0)"
        )
        expressions = {
            ("OT",): "result = payslip.total_overtime_amount or 0.0",
            # LATE is the module default, while existing databases can use LF.
            # Match the fine sign to the installed NET rule's convention so the
            # deduction is applied once rather than becoming an earning.
            ("LATE", "LF"): fine_expression,
            ("PH",): "result = payslip.total_public_holiday_amount or 0.0",
        }
        for codes, expression in expressions.items():
            self.search([("code", "in", codes)]).write({
                "condition_select": "none",
                "amount_select": "code",
                "amount_python_compute": expression,
            })
        return True
