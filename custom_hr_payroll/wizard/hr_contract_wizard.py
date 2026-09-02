from odoo import models, fields, api
from datetime import date

class HrContractWizard(models.TransientModel):
    _name = 'hr.contract.wizard'
    _description = 'Contract Creation Wizard'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    contract_name = fields.Char(string='Contract Name', required=True)
    wage_type = fields.Selection([
        ('daily', 'Daily Wage'),
        ('monthly', 'Monthly Wage'),
        ('hourly', 'Hourly Wage'),
    ], string='Wage Type', default='monthly', required=True)
    wage = fields.Float(string='Wage', required=True)
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date')
    resource_calendar_id = fields.Many2one('resource.calendar', string="Work Schedule")
    structure_type_id = fields.Many2one('hr.payroll.structure.type', string="Salary Structure Type")
    job_id = fields.Many2one('hr.job', string="Job Position")
    department_id = fields.Many2one('hr.department', string="Department")
    contract_type_id = fields.Many2one('hr.contract.type', string="Contract Type")
    struct_id = fields.Many2one('hr.payroll.structure', string="Salary Structure")
    
    is_overtime_allowed = fields.Boolean(string='Is overtime allowed?')
    is_latefine_applicable = fields.Boolean(string='Is latefine applicable?')
    public_holidays_working = fields.Boolean(string="Public Holidays")
    weekend_special_working = fields.Boolean(string="Weekend Days")

    @api.model
    def default_get(self, fields_list):
        res = super(HrContractWizard, self).default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            employee = self.env['hr.employee'].browse(active_id)
            res['employee_id'] = employee.id
            res['contract_name'] = employee.name
            res['resource_calendar_id'] = employee.resource_calendar_id.id
            res['job_id'] = employee.job_id.id
            res['department_id'] = employee.department_id.id
        
        today = date.today()
        res['date_start'] = today.replace(day=1)
        
        # Default Monthly logic
        res['wage_type'] = 'monthly'
        res['is_overtime_allowed'] = True
        res['is_latefine_applicable'] = True
        res['public_holidays_working'] = True
        res['weekend_special_working'] = True
        
        # Default Work Schedule if only one exists
        calendars = self.env['resource.calendar'].search([])
        if len(calendars) == 1:
            res['resource_calendar_id'] = calendars.id
        
        return res

    @api.onchange('wage_type')
    def _onchange_wage_type(self):
        if self.wage_type in ['daily','monthly']:
            self.is_overtime_allowed = True
            self.is_latefine_applicable = True
            self.public_holidays_working = True
            self.weekend_special_working = True
        else:
            self.is_overtime_allowed = False
            self.is_latefine_applicable = False
            self.public_holidays_working = False
            self.weekend_special_working = False

    def action_create_contract(self):
        self.ensure_one()
        # journal_id = self.env["account.journal"].search([("code", "=", "SAL")],limit=1)
        
        vals = {
            'name': self.contract_name,
            'employee_id': self.employee_id.id,
            'wage_type': self.wage_type,
            'date_start': self.date_start,
            'date_end': self.date_end,
            'job_id': self.job_id.id,
            'department_id': self.department_id.id,
            'contract_type_id': self.contract_type_id.id,
            # 'journal_id': journal_id.id,
            'state': 'draft', 
        }
        
        if self.wage_type == 'hourly':
            vals['hourly_rate'] = self.wage
            vals['wage'] = 0.0 
            vals['resource_calendar_id'] = False # No schedule for hourly
            vals['schedule_pay'] = 'hourly' # Set schedule_pay to hourly
        else:
            if self.wage_type == 'monthly':
                vals['wage'] = self.wage
                vals['daily_wage'] = 0
            if self.wage_type == 'daily':
                vals['daily_wage'] = self.wage
                vals['wage'] = 0
            vals['resource_calendar_id'] = self.resource_calendar_id.id
            vals['structure_type_id'] = self.structure_type_id.id
            vals['struct_id'] = self.struct_id.id
            vals['is_overtime_allowed'] = self.is_overtime_allowed
            vals['is_latefine_applicable'] = self.is_latefine_applicable
            vals['public_holidays_working'] = self.public_holidays_working
            vals['weekend_special_working'] = self.weekend_special_working
            vals['schedule_pay'] = 'monthly'

        contract = self.env['hr.contract'].create(vals)
        
        return {
            'name': 'Contract',
            'view_mode': 'form',
            'res_model': 'hr.contract',
            'res_id': contract.id,
            'type': 'ir.actions.act_window',
        }
