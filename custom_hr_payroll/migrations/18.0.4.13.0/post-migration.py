from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Refresh display aggregates only. Saved salary lines and states are intact.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['hr.payslip'].search([])._compute_pay()
