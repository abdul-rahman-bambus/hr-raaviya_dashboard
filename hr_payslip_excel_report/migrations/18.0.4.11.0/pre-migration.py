"""Remove only PR #121's preparation UI before loading the restored report views."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Do not remove payroll batches, payslips, salary lines or payment data.
    # Removing inherited buttons first also avoids validating obsolete method
    # names while the restored Python models and report views are loaded.
    for name in (
        'menu_draft_payroll_preparation',
        'payslip_run_draft_payroll_form',
        'action_draft_payroll_preparation',
        'draft_payroll_preparation_form',
        'access_draft_payroll_preparation',
    ):
        data = env['ir.model.data'].search([
            ('module', '=', 'hr_payslip_excel_report'), ('name', '=', name)])
        if data and data.model in env:
            env[data.model].browse(data.res_id).exists().unlink()
        data.exists().unlink()
