from odoo import fields, models


class HrSalaryRevision(models.Model):
    _inherit = "hr.salary.revision"

    previous_automation_template_id = fields.Many2one(
        "bambus.attendance.automation.template", string="Previous Automation Template"
    )
    revised_automation_template_id = fields.Many2one(
        "bambus.attendance.automation.template", string="Revised Automation Template"
    )


class HrSalaryRevisionWizard(models.TransientModel):
    _inherit = "hr.salary.revision.wizard"

    current_automation_template_id = fields.Many2one(
        related="employee_id.attendance_automation_template_id",
        string="Current Automation Template", readonly=True,
    )
    revised_automation_template_id = fields.Many2one(
        "bambus.attendance.automation.template",
        string="Revised Automation Template",
        domain="[('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(related="payslip_id.company_id", readonly=True)

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        payslip = self.env["hr.payslip"].browse(
            self.env.context.get("default_payslip_id")
        ).exists()
        if payslip:
            values["revised_automation_template_id"] = (
                payslip.employee_id.attendance_automation_template_id.id
            )
        return values

    def _has_additional_term_changes(self):
        self.ensure_one()
        return (
            self.revised_automation_template_id
            != self.current_automation_template_id
        )

    def _prepare_additional_revision_values(self):
        self.ensure_one()
        return {
            "previous_automation_template_id": self.current_automation_template_id.id,
            "revised_automation_template_id": self.revised_automation_template_id.id,
        }

    def _apply_additional_terms(self, revised_contract):
        self.ensure_one()
        self.employee_id.attendance_automation_template_id = (
            self.revised_automation_template_id
        )
