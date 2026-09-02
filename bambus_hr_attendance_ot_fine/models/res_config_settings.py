from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    bambus_ot_mode = fields.Selection(related="company_id.bambus_ot_mode", readonly=False)
