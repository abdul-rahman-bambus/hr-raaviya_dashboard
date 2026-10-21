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
        basic = self.env.ref('hr_payroll_community.hr_rule_basic', raise_if_not_found=False)
        if basic:
            basic.write({
                'amount_select': 'code',
                'amount_python_compute': (
                    "result = (payslip.total_worker_hours * contract.hourly_rate "
                    "if contract.wage_type == 'hourly' else payslip.total_regular_pay_amount "
                    "if payslip.uses_template_regular_pay else contract.wage)"
                ),
            })
        # Existing customers can have separate wage-specific BASIC rules. Keep
        # their conditions and legacy fallback, but use the shared template
        # amount so Daily special-day work is not dropped from salary.
        marker = '# bambus_template_base_v1'
        wage_rules = self.search([('code', 'in', ['BASIC_MONTHLY', 'BASIC_DAILY', 'BASIC_HOURLY']),
                                  ('amount_select', '=', 'code')]) - (basic or self.browse())
        for rule in wage_rules:
            original = rule.amount_python_compute or 'result = 0.0'
            if marker in original:
                continue
            fallback = '\n'.join('    ' + line for line in original.splitlines())
            rule.amount_python_compute = (
                marker + '\n'
                "if contract.wage_type == 'hourly':\n"
                '    result = payslip.total_worker_hours * contract.hourly_rate\n'
                'elif payslip.uses_template_regular_pay:\n'
                '    result = payslip.total_regular_pay_amount\n'
                'else:\n' + fallback
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
