from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class HrSalaryRevisionWizard(models.TransientModel):
    _name = "hr.salary.revision.wizard"
    _description = "Revise Employment Terms"

    payslip_id = fields.Many2one("hr.payslip", required=True, readonly=True)
    employee_id = fields.Many2one(related="payslip_id.employee_id", readonly=True)
    contract_id = fields.Many2one(related="payslip_id.contract_id", readonly=True)
    currency_id = fields.Many2one(related="payslip_id.company_id.currency_id", readonly=True)
    current_wage = fields.Monetary(currency_field="currency_id", readonly=True)
    revised_wage = fields.Monetary(currency_field="currency_id", required=True)
    current_wage_type = fields.Selection(related="contract_id.wage_type", readonly=True)
    revised_wage_type = fields.Selection([
        ("daily", "Daily Wage"), ("monthly", "Monthly Wage"),
        ("hourly", "Hourly Wage"),
    ], required=True)
    current_calendar_id = fields.Many2one(
        related="contract_id.resource_calendar_id", string="Current Working Schedule",
        readonly=True,
    )
    revised_calendar_id = fields.Many2one("resource.calendar", string="Revised Working Schedule")
    difference = fields.Monetary(compute="_compute_change", currency_field="currency_id")
    percentage_change = fields.Float(compute="_compute_change")
    effective_date = fields.Date(required=True)
    reason = fields.Char(required=True)

    def _contract_wage(self, contract, wage_type=None):
        wage_type = wage_type or contract.wage_type
        return {
            "monthly": contract.wage,
            "daily": contract.daily_wage,
            "hourly": contract.hourly_rate,
        }.get(wage_type, 0.0)

    @api.onchange("revised_wage_type")
    def _onchange_revised_wage_type(self):
        if self.contract_id:
            self.revised_wage = self._contract_wage(
                self.contract_id, self.revised_wage_type
            )

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
                "current_wage": self._contract_wage(payslip.contract_id),
                "revised_wage": self._contract_wage(payslip.contract_id),
                "revised_wage_type": payslip.contract_id.wage_type,
                "revised_calendar_id": payslip.contract_id.resource_calendar_id.id,
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
        if self.effective_date != payslip.date_from:
            raise ValidationError(_("The effective date must be the first day of this payslip period."))
        if self.revised_wage <= 0:
            raise ValidationError(_("Revised wage or rate must be greater than zero."))
        if self.revised_wage_type != "hourly" and not self.revised_calendar_id:
            raise ValidationError(_("Select a working schedule for daily or monthly employees."))
        previous_wage = self._contract_wage(contract)
        previous_wage_type = contract.wage_type
        previous_calendar = contract.resource_calendar_id
        if (
            self.revised_wage_type == contract.wage_type
            and self.revised_wage == previous_wage
            and self.revised_calendar_id == contract.resource_calendar_id
            and not self._has_additional_term_changes()
        ):
            raise ValidationError(_("Change at least one employment term before applying."))

        contract_values = self._prepare_contract_values()
        revised_contract = contract
        if self.revised_wage_type != contract.wage_type and self.effective_date > contract.date_start:
            contract.write({"date_end": self.effective_date - timedelta(days=1)})
            revised_contract = contract.copy({
                **contract_values,
                "name": _("%s - revised %s", contract.name, self.effective_date),
                "date_start": self.effective_date,
                "date_end": False,
            })
            payslip.contract_id = revised_contract
        else:
            contract.write(contract_values)
        self.employee_id.resource_calendar_id = self.revised_calendar_id

        self.env["hr.salary.revision"].create({
            "employee_id": self.employee_id.id,
            "contract_id": revised_contract.id,
            "source_contract_id": contract.id,
            "revised_contract_id": revised_contract.id,
            "payslip_id": payslip.id,
            "previous_wage": previous_wage,
            "revised_wage": self.revised_wage,
            "previous_wage_type": previous_wage_type,
            "revised_wage_type": self.revised_wage_type,
            "previous_calendar_id": previous_calendar.id,
            "revised_calendar_id": self.revised_calendar_id.id,
            "effective_date": self.effective_date,
            "reason": self.reason,
            "revised_by_id": self.env.user.id,
            "revised_on": fields.Datetime.now(),
            **self._prepare_additional_revision_values(),
        })
        self._apply_additional_terms(revised_contract)
        payslip.action_compute_sheet()
        return {"type": "ir.actions.client", "tag": "reload"}

    def _prepare_contract_values(self):
        values = {
            "wage_type": self.revised_wage_type,
            "resource_calendar_id": self.revised_calendar_id.id or False,
            "wage": self.revised_wage if self.revised_wage_type == "monthly" else 0.0,
            "daily_wage": self.revised_wage if self.revised_wage_type == "daily" else 0.0,
            "hourly_rate": self.revised_wage if self.revised_wage_type == "hourly" else 0.0,
            "schedule_pay": "hourly" if self.revised_wage_type == "hourly" else "monthly",
        }
        return values

    def _has_additional_term_changes(self):
        return False

    def _prepare_additional_revision_values(self):
        return {}

    def _apply_additional_terms(self, revised_contract):
        return None
