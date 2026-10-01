from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class HrSalaryRevisionWizard(models.TransientModel):
    _name = "hr.salary.revision.wizard"
    _description = "Revise Monthly Salary"

    payslip_id = fields.Many2one("hr.payslip", required=True, readonly=True)
    employee_id = fields.Many2one(related="payslip_id.employee_id", readonly=True)
    contract_id = fields.Many2one(related="payslip_id.contract_id", readonly=True)
    currency_id = fields.Many2one(related="payslip_id.company_id.currency_id", readonly=True)
    current_wage = fields.Monetary(currency_field="currency_id", readonly=True)
    revised_wage = fields.Monetary(currency_field="currency_id", required=True)
    difference = fields.Monetary(compute="_compute_change", currency_field="currency_id")
    percentage_change = fields.Float(compute="_compute_change")
    effective_date = fields.Date(required=True)
    reason = fields.Char(required=True)

    @api.depends("current_wage", "revised_wage")
    def _compute_change(self):
        for wizard in self:
            wizard.difference = wizard.revised_wage - wizard.current_wage
            wizard.percentage_change = (
                wizard.difference / wizard.current_wage
                if wizard.current_wage else 0.0
            )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        payslip = self.env["hr.payslip"].browse(
            self.env.context.get("default_payslip_id")
        ).exists()
        if payslip:
            values.update({
                "payslip_id": payslip.id,
                "current_wage": payslip.contract_id.wage,
                "revised_wage": payslip.contract_id.wage,
                "effective_date": payslip.date_from,
            })
        return values

    def action_apply_revision(self):
        self.ensure_one()
        payslip = self.payslip_id
        contract = self.contract_id
        if payslip.state != "draft":
            raise UserError(_("Salary can only be revised from a draft payslip."))
        if not contract:
            raise UserError(_("Select a contract on the payslip before revising salary."))
        if contract.wage_type != "monthly":
            raise UserError(_("This revision flow currently supports monthly contracts only."))
        if self.effective_date != payslip.date_from:
            raise ValidationError(_("The effective date must be the first day of this payslip period."))
        if self.revised_wage <= 0:
            raise ValidationError(_("Revised monthly salary must be greater than zero."))
        previous_wage = contract.wage
        if self.revised_wage == previous_wage:
            raise ValidationError(_("Enter a revised salary different from the current salary."))

        self.env["hr.salary.revision"].create({
            "employee_id": self.employee_id.id,
            "contract_id": contract.id,
            "payslip_id": payslip.id,
            "previous_wage": previous_wage,
            "revised_wage": self.revised_wage,
            "effective_date": self.effective_date,
            "reason": self.reason,
            "revised_by_id": self.env.user.id,
            "revised_on": fields.Datetime.now(),
        })
        contract.write({"wage": self.revised_wage})
        payslip.action_compute_sheet()
        return {"type": "ir.actions.client", "tag": "reload"}
