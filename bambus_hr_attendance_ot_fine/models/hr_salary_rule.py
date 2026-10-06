from odoo import api, models


class HrSalaryRule(models.Model):
    _inherit = "hr.salary.rule"

    @api.model
    def _bambus_use_automation_amounts(self):
        """Move attendance adjustments to the approved template snapshots.

        Public-holiday work is already included in the approved overtime total.
        Keeping a second PH calculation would both depend on obsolete contract
        switches and pay the same work twice.
        """
        expressions = {
            ("OT",): "result = payslip.total_overtime_amount or 0.0",
            # LATE is the module default, while existing databases can use LF.
            # Both codes represent the same attendance-fine deduction.
            ("LATE", "LF"): "result = -(payslip.total_fine_amount or 0.0)",
            ("PH",): "result = 0.0",
        }
        for codes, expression in expressions.items():
            self.search([("code", "in", codes)]).write({
                "condition_select": "none",
                "amount_select": "code",
                "amount_python_compute": expression,
            })
        return True
