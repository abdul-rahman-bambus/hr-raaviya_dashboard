
from odoo import _, models, fields, api
from datetime import timedelta
from odoo.exceptions import ValidationError


class HrContract(models.Model):
    _inherit = "hr.contract"

    wage_type = fields.Selection([
        ('daily', 'Daily Wage'),
        ('monthly', 'Monthly Wage'),
        ('hourly', 'Hourly Wage'),
    ], string='Wage Type', default='monthly')
    daily_wage = fields.Float(string="Wage / Day")

    hourly_rate = fields.Float(string='Hourly Rate')
    hour_source = fields.Selection([
        ('attendance', 'Attendance'),
        # ('timesheet', 'Timesheet'),
    ], string='Source', default='attendance')

    overtime_rate = fields.Float(string='Overtime / Hour', default=0)
    is_latefine_applicable = fields.Boolean(string='Is latefine applicable?', default=False)
    apply_late_fine = fields.Selection([
        ('fixed', 'Fixed'),
        ('wage_based', 'Wage Based Deduction'),
    ],string='Apply Late Fine')
    is_overtime_allowed = fields.Boolean(string='Is overtime allowed?', default=False)
    late_fine_rate = fields.Float(string='Late fine / minute', default=0)
    
    public_holidays_working = fields.Boolean(string="Public Holidays")
    public_holiday_wage_type = fields.Selection([
        ('fixed', 'Fixed'),
        ('wage_based', 'Wage Based'),
    ], string='Pay Type', default='fixed')   
    public_holiday_wage_rate = fields.Float(string="Pay Rate")

    weekend_special_working = fields.Boolean(
    string="Weekend Days",
    help="If enabled, special pay rules apply when working on configured weekend days"
        )
    weekend_wage_type = fields.Selection([
        ('normal', 'Regular Pay'),
        ('fixed', 'Fixed Allowance'),
        ('wage_based', 'Wage Based Allowance'),
    ], string="Pay Type")

    weekend_wage_rate = fields.Float(
        string="Weekend Pay Rate",
        help="Fixed rate OR multiplication factor depending on weekend wage type"
    )
    hourly_wage_hour_limit = fields.Float(
        string="Hourly Wage Hour Limit",
        help="Hourly wage hour limit, set it 0 if all 24 hours can be worked per day. The employee cannot be billed beyound this time.",
        default=lambda self: float(
            self.env['ir.config_parameter'].sudo().get_param('hr_payroll.hourly_wage_hour_limit', 0.0)
        ),
    )

    @api.constrains('sunday_wage_rate', 'saturday_wage_rate')
    def _check_wage_rate(self):
        """Function to add constrains for wage rate field not to increase more than 2"""
        if self.saturday_wage_rate > 2 or self.sunday_wage_rate > 2:
            raise ValidationError(
                _('Error! Please do not add Wage Rate more than 2'))
