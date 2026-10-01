from odoo import api, fields, models


class HrSalaryRevision(models.Model):
    _name = "hr.salary.revision"
    _description = "Salary Revision History"
    _order = "effective_date desc, id desc"

    employee_id = fields.Many2one("hr.employee", required=True, index=True, ondelete="cascade")
    contract_id = fields.Many2one("hr.contract", required=True, index=True, ondelete="cascade")
    payslip_id = fields.Many2one("hr.payslip", index=True, ondelete="set null")
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    previous_wage = fields.Monetary(required=True, currency_field="currency_id")
    revised_wage = fields.Monetary(required=True, currency_field="currency_id")
    difference = fields.Monetary(compute="_compute_change", store=True, currency_field="currency_id")
    percentage_change = fields.Float(compute="_compute_change", store=True)
    effective_date = fields.Date(required=True, index=True)
    reason = fields.Char()
    revised_by_id = fields.Many2one("res.users", required=True, readonly=True)
    revised_on = fields.Datetime(required=True, readonly=True)

    @api.depends("previous_wage", "revised_wage")
    def _compute_change(self):
        for revision in self:
            revision.difference = revision.revised_wage - revision.previous_wage
            revision.percentage_change = (
                revision.difference / revision.previous_wage
                if revision.previous_wage else 0.0
            )


class HrContract(models.Model):
    _inherit = "hr.contract"

    salary_revision_ids = fields.One2many(
        "hr.salary.revision", "contract_id", string="Salary Revision History"
    )


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def action_open_salary_revision(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Revise Salary",
            "res_model": "hr.salary.revision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payslip_id": self.id},
        }
