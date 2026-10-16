"""One HR review for a day's earnings and individual fine components."""
import math
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttendanceReviewWizard(models.TransientModel):
    _name = 'bambus.hr.attendance.review.wizard'
    _inherit = 'bambus.hr.overtime.wizard'
    _description = 'Review Attendance Adjustments'

    contract_wage_label = fields.Char(compute="_compute_contract_wage")
    contract_wage_amount = fields.Monetary(compute="_compute_contract_wage", currency_field="currency_id")

    @api.depends('line_id.contract_id.wage_type', 'line_id.contract_id.wage',
                 'line_id.contract_id.daily_wage', 'line_id.contract_id.hourly_rate')
    def _compute_contract_wage(self):
        for wizard in self:
            wizard.contract_wage_label, wizard.contract_wage_amount = wizard._contract_wage(wizard.line_id.contract_id)

    @api.model
    def _contract_wage(self, contract):
        if not contract:
            return _("No Contract"), 0.0
        label, field = {
            'daily': (_('Daily Wage'), 'daily_wage'),
            'hourly': (_('Hourly Rate'), 'hourly_rate'),
            'monthly': (_('Monthly Wage'), 'wage'),
        }.get(contract.wage_type, (_('Monthly Wage'), 'wage'))
        return label, contract[field] or 0.0

    show_overtime = fields.Boolean(readonly=True)
    ignore_overtime = fields.Boolean(string='Ignore Overtime')
    fine_line_ids = fields.One2many('bambus.hr.attendance.review.fine', 'wizard_id')
    initial_fines = fields.Json(readonly=True)
    source_write_date = fields.Datetime(readonly=True)

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        line = self.env['bambus.hr.attendance.sheet.line'].browse(values.get('line_id')).exists()
        if not line:
            return values
        line._check_review_access()
        atts = line._review_attendances()
        last = atts[-1:]
        snapshots = line.fine_review_data or {}
        fine_default = self.env['bambus.hr.fine.wizard'].with_context(default_line_id=line.id).new({})
        template = line.employee_id._get_attendance_automation_template(line.date)
        if snapshots and template:
            fine_default = self.env['bambus.hr.fine.wizard'].new({
                'line_id': line.id, 'fine_hours': last.bambus_fine_hours if last else 0,
                'calculation_type': template.fine_calculation_type, 'rate': template.fine_rate,
            })
        # Preserve an earlier aggregate HR approval rather than inventing a split.
        if not snapshots and line.fine_state == 'approved':
            components = {'fine': line.fine_hours}
        elif line.fine_state == 'rejected' and not snapshots:
            components = {}
        else:
            components = {
                'late': (last.bambus_late_minutes or 0) / 60 if last else 0,
                'break': (last.bambus_gap_minutes or 0) / 60 if last else 0,
                'early': (last.bambus_early_leave_minutes or 0) / 60 if last else 0,
            }
            total = sum(components.values())
            detected = (last.bambus_fine_hours or 0) if last else 0
            if total and detected < total:
                components = {kind: hours * detected / total for kind, hours in components.items()}
            if not total and detected:
                components = {'fine': detected}
        fixed_allocations = {}
        if fine_default.calculation_type in ('fixed', 'half_day', 'full_day'):
            active = [(kind, hours) for kind, hours in components.items() if hours > 0]
            total_hours = sum(hours for _, hours in active)
            remaining = fine_default.fine_amount
            for index, (kind, hours) in enumerate(active):
                amount = remaining if index == len(active) - 1 else line.currency_id.round(fine_default.fine_amount * hours / total_hours)
                fixed_allocations[kind] = amount
                remaining -= amount
        rows = []
        initial = dict(snapshots)
        for kind in dict.fromkeys([*components, *snapshots]):
            saved = snapshots.get(kind, {})
            if saved.get('state') == 'ignored':
                continue
            hours = saved.get('hours', components.get(kind, 0))
            if not hours and not saved.get('amount'):
                continue
            row = {
                'kind': kind, 'hours': hours,
                'detected_hours': components.get(kind, hours),
                'calculation_type': saved.get('calculation_type', fine_default.calculation_type),
                'rate': saved.get('rate', fine_default.rate), 'note': saved.get('note', ''),
            }
            if not saved and fine_default.calculation_type in ('fixed', 'half_day', 'full_day'):
                row.update(calculation_type='fixed', rate=fixed_allocations.get(kind, 0))
            if kind == 'fine' and not snapshots and line.fine_state == 'approved':
                row.update(calculation_type='fixed', rate=line.fine_amount)
            rows.append((0, 0, row))
            initial[kind] = saved or {'state': 'pending', 'hours': hours}
        values.update({
            'fine_line_ids': rows, 'initial_fines': initial,
            'source_write_date': line.write_date,
            'show_overtime': bool(line.contract_id.wage_type in ('daily', 'monthly')
                                  and line.overtime_state != 'rejected'
                                  and (line.overtime_hours or line.overtime_detected_hours)),
            'ignore_overtime': line.overtime_state == 'rejected',
        })
        return values

    def action_save(self):
        self.ensure_one()
        line = self.line_id
        line._check_review_access()
        if self.source_write_date and line.write_date != self.source_write_date:
            raise UserError(_('Attendance review changed. Close and reopen this review before approving.'))
        if self.show_overtime:
            if not all(math.isfinite(value) and value >= 0 for value in (self.overtime_hours, self.rate)):
                raise UserError(_('Hours and rates must be finite, nonnegative numbers.'))
            if self.ignore_overtime:
                line.write({'overtime_hours': 0, 'overtime_amount': 0, 'overtime_state': 'rejected',
                            'overtime_updated_by_id': self.env.uid, 'overtime_updated_on': fields.Datetime.now()})
            else:
                super().action_save()
        data = dict(self.initial_fines or {})
        retained = set(self.fine_line_ids.mapped('kind'))
        if len(retained) != len(self.fine_line_ids):
            raise UserError(_('Each fine component may appear only once.'))
        for kind in set(data) - retained:
            data[kind] = dict(data[kind], state='ignored', amount=0, hours=0)
        for row in self.fine_line_ids:
            if row.kind not in data:
                raise UserError(_('Close and reopen the review to refresh fine components.'))
            if not all(math.isfinite(value) and value >= 0 for value in (row.hours, row.rate)):
                raise UserError(_('Hours and rates must be finite, nonnegative numbers.'))
            data[row.kind] = {
                'state': 'approved', 'hours': row.hours, 'amount': row.amount,
                'calculation_type': row.calculation_type, 'rate': row.rate, 'note': row.note or '',
            }
        if data:
            previous = line.fine_hours
            line.write({
                'fine_review_data': data, 'fine_hours': sum(row.hours for row in self.fine_line_ids),
                'fine_amount': sum(row.amount for row in self.fine_line_ids),
                'fine_detected_hours': sum(row.detected_hours for row in self.fine_line_ids),
                'fine_state': 'approved' if self.fine_line_ids else 'rejected',
                'fine_calculation_type': 'fixed', 'fine_rate': sum(self.fine_line_ids.mapped('amount')),
                'fine_updated_by_id': self.env.uid, 'fine_updated_on': fields.Datetime.now(),
            })
            self.env['bambus.hr.attendance.time.audit'].create({
                'employee_id': line.employee_id.id, 'date': line.date, 'adjustment_type': 'fine',
                'previous_hours': previous, 'adjusted_hours': line.fine_hours, 'updated_by_id': self.env.uid,
            })
        return {'type': 'ir.actions.act_window_close'}


class AttendanceReviewFine(models.TransientModel):
    _name = 'bambus.hr.attendance.review.fine'
    _description = 'Attendance Review Fine Component'

    wizard_id = fields.Many2one('bambus.hr.attendance.review.wizard', required=True, ondelete='cascade')
    kind = fields.Selection([('late', 'Late Fine'), ('break', 'Break / Gap Fine'),
                             ('early', 'Early Exit Fine'), ('fine', 'Previously Combined Fine')], required=True)
    detected_hours = fields.Float(readonly=True, digits=(16, 6))
    hours = fields.Float(string='Final Hours', digits=(16, 6))
    calculation_type = fields.Selection(selection=lambda self: self.env['bambus.hr.fine.wizard']._fields['calculation_type']._description_selection(self.env), required=True)
    rate = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    amount = fields.Monetary(compute='_compute_amount', currency_field='currency_id')
    note = fields.Char()

    @api.depends('hours', 'calculation_type', 'rate', 'wizard_id.line_id.contract_id')
    def _compute_amount(self):
        for row in self:
            helper = self.env['bambus.hr.fine.wizard'].new({
                'line_id': row.wizard_id.line_id.id, 'fine_hours': row.hours,
                'calculation_type': row.calculation_type, 'rate': row.rate,
            })
            row.amount = helper.fine_amount


class AttendanceReviewLine(models.Model):
    _inherit = 'bambus.hr.attendance.sheet.line'

    fine_review_data = fields.Json(copy=False, default=dict)

    def _check_review_access(self):
        self.ensure_one()
        if not self.env.user.has_group('hr.group_hr_user') or self.company_id not in self.env.companies:
            raise UserError(_('Only HR officers of the selected company can approve attendance.'))
        self.check_access('write')

    def _day_bounds_utc(self, day):
        self.ensure_one()
        calendar = self.contract_id.resource_calendar_id or self.employee_id.resource_calendar_id
        tz = pytz.timezone(calendar.tz or self.env.user.tz or 'UTC')
        start = tz.localize(datetime.combine(day, time.min))
        end = tz.localize(datetime.combine(day + timedelta(days=1), time.min))
        return start.astimezone(pytz.UTC).replace(tzinfo=None), end.astimezone(pytz.UTC).replace(tzinfo=None)

    def _review_attendances(self):
        self.ensure_one()
        start, end = self._day_bounds_utc(self.date)
        return self.env['hr.attendance'].search([
            ('employee_id', '=', self.employee_id.id), ('check_in', '>=', start), ('check_in', '<', end),
        ], order='check_in, id')

    def action_review_adjustments(self):
        self.ensure_one()
        self._check_review_access()
        return {
            'type': 'ir.actions.act_window', 'name': _('Review Attendance Adjustments'),
            'res_model': 'bambus.hr.attendance.review.wizard', 'view_mode': 'form', 'target': 'new',
            'views': [(self.env.ref('bambus_hr_daily_ops.view_attendance_review_wizard').id, 'form')],
            'context': {'default_line_id': self.id},
        }


class AttendanceReviewDashboard(models.Model):
    _inherit = 'bambus.hr.attendance.sheet'

    @api.model
    def get_dashboard_review(self, employee_id, selected_date):
        action = self.open_dashboard_adjustment(employee_id, selected_date, 'fine')
        line = self.env['bambus.hr.attendance.sheet.line'].browse(action['context']['default_line_id'])
        wizard = self.env['bambus.hr.attendance.review.wizard'].with_context(default_line_id=line.id).create({})
        daily_rate, hourly_rate = wizard._contract_rates(line)
        items = []
        if wizard.show_overtime:
            items.append({
                'id': 'overtime', 'label': _('Overtime'), 'hours': wizard.overtime_hours,
                'detected_hours': wizard.detected_overtime_hours, 'rate': wizard.rate,
                'calculation_type': wizard.calculation_type, 'note': wizard.note or '',
                'calculation_options': wizard._fields['calculation_type']._description_selection(self.env),
            })
        for row in wizard.fine_line_ids:
            items.append({
                'id': row.id, 'label': dict(row._fields['kind']._description_selection(self.env))[row.kind],
                'hours': row.hours, 'detected_hours': row.detected_hours, 'rate': row.rate,
                'calculation_type': row.calculation_type, 'note': row.note or '',
                'calculation_options': row._fields['calculation_type']._description_selection(self.env),
            })
        fine = self.env['bambus.hr.fine.wizard'].new({'line_id': line.id})
        currency = wizard.currency_id
        wage_label, wage_amount = wizard._contract_wage(line.contract_id)
        return {
            'wizard_id': wizard.id, 'adjustment': 'review', 'employee': line.employee_id.name,
            'date': fields.Date.to_string(line.date), 'items': items,
            'contract_wage_label': wage_label, 'contract_wage_amount': wage_amount,
            'daily_rate': daily_rate, 'hourly_rate': hourly_rate, 'salary_per_minute': fine.salary_per_minute,
            'currency': {'symbol': currency.symbol or '', 'position': currency.position or 'before',
                         'decimal_places': currency.decimal_places},
        }

    @api.model
    def save_dashboard_review(self, wizard_id, items):
        wizard = self.env['bambus.hr.attendance.review.wizard'].browse(wizard_id).exists()
        if not wizard or wizard.create_uid != self.env.user:
            raise UserError(_('This attendance review has expired. Open it again.'))
        wizard.line_id._check_review_access()
        allowed = {row.id: row for row in wizard.fine_line_ids}
        seen = set()
        commands = []
        for item in items:
            key = item.get('id')
            if key in seen or key not in {*allowed, 'overtime'}:
                raise UserError(_('Invalid review item. Close and reopen the review.'))
            seen.add(key)
            try:
                hours, rate = float(item.get('hours', 0)), float(item.get('rate', 0))
            except (ValueError, TypeError):
                raise UserError(_('Enter valid hours and rate values.'))
            if not all(math.isfinite(value) and value >= 0 for value in (hours, rate)):
                raise UserError(_('Hours and rates must be finite, nonnegative numbers.'))
            values = {'calculation_type': item.get('calculation_type'), 'rate': rate, 'note': item.get('note') or False}
            if key == 'overtime':
                if not wizard.show_overtime:
                    raise UserError(_('No overtime is available for approval.'))
                wizard.write(dict(values, overtime_hours=hours))
            else:
                commands.append((1, key, dict(values, hours=hours)))
        commands.extend((2, key) for key in allowed if key not in seen)
        wizard.write({'fine_line_ids': commands, 'ignore_overtime': 'overtime' not in seen})
        return wizard.action_save()
