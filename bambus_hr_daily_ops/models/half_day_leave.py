"""Explicit HR half-day requests with schedule-based suggestions."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HalfDayLeaveWizard(models.TransientModel):
    _name = 'bambus.hr.half.day.leave.wizard'
    _description = 'Confirm Half Day Leave'

    employee_id = fields.Many2one('hr.employee', required=True, readonly=True)
    company_id = fields.Many2one(related='employee_id.company_id')
    date = fields.Date(required=True, readonly=True)
    period = fields.Selection([('am', 'First Half'), ('pm', 'Second Half')], required=True)
    leave_type_id = fields.Many2one('hr.leave.type', string='Time Off Type', required=True,
                                  domain="[('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    explanation = fields.Char(readonly=True)

    def _check_employee_access(self):
        self.ensure_one()
        if (not self.env.user.has_group('hr.group_hr_user')
                or self.employee_id.company_id not in self.env.companies):
            raise UserError(_('Only HR officers of the selected company can create time off.'))
        self.employee_id.check_access('read')

    def action_confirm(self):
        self.ensure_one()
        self._check_employee_access()
        leave_type = self.leave_type_id
        if (not self.period or not leave_type.active
                or (leave_type.company_id and leave_type.company_id != self.employee_id.company_id)):
            raise UserError(_('Select the leave half and an active time off type for this company.'))
        Leave = self.env['hr.leave'].sudo()
        if Leave.search_count([('employee_id', '=', self.employee_id.id),
                               ('state', 'not in', ['refuse', 'cancel']),
                               ('request_date_from', '<=', self.date), ('request_date_to', '>=', self.date)]):
            raise UserError(_('A time off request already covers this date. Open it instead.'))
        leave = Leave.create({'employee_id': self.employee_id.id, 'holiday_status_id': leave_type.id,
                              'request_date_from': self.date, 'request_date_to': self.date,
                              'request_unit_half': True, 'request_date_from_period': self.period,
                              'name': _('Half Day Leave')})
        if leave.state == 'draft':
            leave.action_confirm()
        # Normal Time Off approval still applies. No blanket auto-validation.
        return {'type': 'ir.actions.act_window_close'}


class HalfDayLeaveDashboard(models.AbstractModel):
    _inherit = 'bambus.attendance.dashboard'

    @api.model
    def prepare_half_day_leave(self, employee_id, selected_date):
        employee = self.env['hr.employee'].browse(employee_id).exists()
        day = fields.Date.to_date(selected_date)
        if not employee or not day:
            raise UserError(_('Select an employee and attendance date.'))
        wizard = self.env['bambus.hr.half.day.leave.wizard'].new({'employee_id': employee.id, 'date': day})
        wizard._check_employee_access()
        existing = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id), ('state', 'not in', ['refuse', 'cancel']),
            ('request_date_from', '<=', day), ('request_date_to', '>=', day),
        ], limit=1)
        if existing:
            return {'type': 'ir.actions.act_window', 'name': _('Existing Time Off'),
                    'res_model': 'hr.leave', 'res_id': existing.id, 'views': [(False, 'form')], 'target': 'new'}
        halves = employee._attendance_leave_half_sessions(day)
        sessions = sorted(halves['am'] + halves['pm'])
        period = False
        if halves['am'] and halves['pm']:
            start, end = sessions[0][0], sessions[-1][1]
            atts = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id), ('check_in', '<', end),
                '|', ('check_out', '=', False), ('check_out', '>', start),
            ])
            if atts and all(att.check_out for att in atts):
                first = any(att.check_in < b and att.check_out > a for att in atts for a, b in halves['am'])
                second = any(att.check_in < b and att.check_out > a for att in atts for a, b in halves['pm'])
                if first != second:
                    period = 'pm' if first else 'am'
        return {'type': 'ir.actions.act_window', 'name': _('Confirm Half Day Leave'),
                'res_model': 'bambus.hr.half.day.leave.wizard', 'views': [(False, 'form')], 'target': 'new',
                'context': {'default_employee_id': employee.id, 'default_date': fields.Date.to_string(day),
                            'default_period': period,
                            'default_explanation': (_('Suggested missing half from completed attendance; confirm the half and paid/unpaid type.')
                                                    if period else _('Attendance is ambiguous. Select the half and paid/unpaid type explicitly.'))}}
