from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    is_monday_weekend = fields.Boolean(string="Monday", config_parameter="hr_payroll.weekend_mon")
    is_tuesday_weekend = fields.Boolean(string="Tuesday", config_parameter="hr_payroll.weekend_tue")
    is_wednesday_weekend = fields.Boolean(string="Wednesday", config_parameter="hr_payroll.weekend_wed")
    is_thursday_weekend = fields.Boolean(string="Thursday", config_parameter="hr_payroll.weekend_thu")
    is_friday_weekend = fields.Boolean(string="Friday", config_parameter="hr_payroll.weekend_fri")
    is_saturday_weekend = fields.Boolean(string="Saturday", config_parameter="hr_payroll.weekend_sat")
    is_sunday_weekend = fields.Boolean(string="Sunday", config_parameter="hr_payroll.weekend_sun")

    late_login_grace_minutes = fields.Integer(string='Late Login Grace Period', 
        config_parameter="custom_hr_payroll.late_login_grace_minutes",
        help="Number of minutes allowed for late login.",
        default=0)

    half_day_hours = fields.Float(
    string="Half Day Threshold (hrs)",
    config_parameter="hr_payroll.half_day_hours",
    default=0.0)

    full_day_hours = fields.Float(
        string="Full Day Threshold (hrs)",
        config_parameter="hr_payroll.full_day_hours",
        default=0.0)
    
    hourly_wage_hour_limit = fields.Float(
        string="Hourly Wage Hour Limit",
        help="Hourly wage hour limit, set it 0 if all 24 hours can be worked per day. The employee cannot be billed beyound this time.",
        config_parameter="hr_payroll.hourly_wage_hour_limit",
    )

    ot_for_weekend_and_festival = fields.Boolean(
            string="OT for Weekend and Festival",
            help="Does Overtime apply for Weekends and Festivals?",
            config_parameter="hr_payroll.ot_for_weekend_and_festival",
        )
    

    declaration_content = fields.Html(related='company_id.declaration_content', readonly=False)

class ResCompany(models.Model):
    _inherit = "res.company"

    declaration_content = fields.Html(string="Employee Declaration Content")
