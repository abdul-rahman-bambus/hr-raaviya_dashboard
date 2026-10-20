from odoo import fields, models


class AttendancePaidDayDecision(models.Model):
    _name = 'bambus.attendance.paid.day.decision'
    _description = 'Paid special-day decision history'
    _order = 'id desc'

    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    date = fields.Date(required=True, index=True)
    kind = fields.Selection([
        ('weekly_off', 'Weekly Off'), ('public_holiday', 'Public Holiday'),
    ], required=True)
    action = fields.Selection([
        ('withhold', 'Withhold Paid Day'), ('restore', 'Restore Paid Day'),
    ], required=True)
    reason = fields.Text(required=True)
    actor_id = fields.Many2one('res.users', required=True, ondelete='restrict')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    paid_day_decision_ids = fields.One2many(
        'bambus.attendance.paid.day.decision', 'employee_id', groups='hr.group_hr_user')

    def _get_paid_day_decision(self, day, kind):
        self.ensure_one()
        return self.env['bambus.attendance.paid.day.decision'].sudo().search([
            ('employee_id', '=', self.id), ('date', '=', day), ('kind', '=', kind),
        ], order='id desc', limit=1)

    def _is_paid_day_withheld(self, day, kind):
        return self._get_paid_day_decision(day, kind).action == 'withhold'
