from odoo import fields, models

class ResCompany(models.Model):
    _inherit = "res.company"

    bambus_ot_mode = fields.Selection([
        ("odoo", "Default"),
        ("custom", "Custom (Worked - Scheduled - Late)"),
    ], default="odoo", string="Overtime Mode")
