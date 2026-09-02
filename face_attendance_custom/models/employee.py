
from odoo import api, models, fields

class HrAEmployeeInherit(models.Model):
    _inherit = "hr.employee"
    
    is_enrolled=fields.Boolean("Is Enrolled")
    last_photo_update_time=fields.Datetime("Last photo update time",default=fields.Datetime.now())
    
