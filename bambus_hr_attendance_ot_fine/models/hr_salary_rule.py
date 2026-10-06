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
        expressions = {
            ("OT",): "result = payslip.total_overtime_amount or 0.0",
            # LATE is the module default, while existing databases can use LF.
            # Both codes represent the same attendance-fine deduction.
            ("LATE", "LF"): "result = -(payslip.total_fine_amount or 0.0)",
            ("PH",): "result = payslip.total_public_holiday_amount or 0.0",
        }
        for codes, expression in expressions.items():
            self.search([("code", "in", codes)]).write({
                "condition_select": "none",
                "amount_select": "code",
                "amount_python_compute": expression,
            })
        return True
