"""Invalidate affected financial decisions after real punch changes, retaining evidence."""
from copy import deepcopy

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttendanceRevision(models.Model):
    _inherit = 'hr.attendance'

    def _revision_keys(self):
        return {(att.employee_id.id, att._bambus_local_day(value))
                for att in self if att.employee_id
                for value in (att.check_in, att.check_out) if value}

    def _revision_punches(self):
        return [{'id': att.id, 'employee_id': att.employee_id.id,
                 'check_in': fields.Datetime.to_string(att.check_in) or False,
                 'check_out': fields.Datetime.to_string(att.check_out) or False} for att in self]

    def _revision_proposal(self, review):
        punches = review._review_attendances()
        components = review.employee_id._attendance_exception_components(review.date)
        fine = sum(punches.mapped('bambus_fine_hours'))
        if review.employee_id._fine_only_attendance_context(review.date) is not None:
            fine = sum(item['hours'] for item in (components or {}).values())
        return {
            'overtime': {'hours': round(max(sum(punches.mapped('overtime_hours')), 0), 6),
                         'amount': round(sum(punches.mapped('bambus_overtime_amount')), 6)},
            'fine': {'hours': round(fine, 6),
                     'amount': round(sum(punches.mapped('bambus_fine_amount')), 6),
                     'components': components,
                     'late': sum(punches.mapped('bambus_late_minutes')),
                     'early': sum(punches.mapped('bambus_early_leave_minutes')),
                     'gap': sum(punches.mapped('bambus_gap_minutes'))},
        }

    def _revision_before(self, keys):
        snapshots = {}
        for employee_id, day in sorted(keys):
            review = self.env['bambus.attendance.day.review'].sudo().search([
                ('employee_id', '=', employee_id), ('date', '=', day)], limit=1)
            if review:
                # Serialize a simultaneous punch edit and HR approval on this day.
                self.env.cr.execute('SELECT id FROM bambus_attendance_day_review WHERE id = %s FOR UPDATE', [review.id])
                review.invalidate_recordset()
                snapshots[(employee_id, day)] = (review, deepcopy(self._revision_proposal(review)))
        return snapshots

    def _revision_finish(self, keys, snapshots, previous, current, operation):
        if previous == current:
            return
        Audit = self.env['bambus.hr.attendance.time.audit'].sudo()
        reason = self.env.context.get('attendance_change_reason') or _('Punch %s', operation)
        for employee_id, day in sorted(keys):
            old = next((row for row in previous if row['employee_id'] == employee_id), {})
            new = next((row for row in current if row['employee_id'] == employee_id), {})
            before_rows = [row for row in previous if row['employee_id'] == employee_id]
            after_rows = [row for row in current if row['employee_id'] == employee_id]
            details = reason
            if max(len(before_rows), len(after_rows)) > 1:
                details += ' | Before: ' + str(before_rows) + ' | After: ' + str(after_rows)
            Audit.create({'employee_id': employee_id, 'date': day, 'adjustment_type': 'attendance',
                'previous_check_in': old.get('check_in'), 'previous_check_out': old.get('check_out'),
                'check_in': new.get('check_in'), 'check_out': new.get('check_out'),
                'updated_by_id': self.env.uid, 'change_details': details,
                'punch_changes': {'operation': operation,
                    'before': [row for row in previous if row['employee_id'] == employee_id],
                    'after': [row for row in current if row['employee_id'] == employee_id]}})
            if (employee_id, day) not in snapshots:
                continue
            review, before = snapshots[(employee_id, day)]
            after = self._revision_proposal(review)
            for kind in ('fine', 'overtime'):
                if before[kind] == after[kind] or review[kind + '_state'] not in ('approved', 'rejected'):
                    continue
                saved = review._revision_decision(kind)
                hours = max(after[kind]['hours'], 0)
                Audit.create({'employee_id': employee_id, 'date': day, 'adjustment_type': kind,
                    'previous_hours': saved['hours'], 'adjusted_hours': hours,
                    'updated_by_id': self.env.uid, 'previous_review': saved,
                    'current_proposal': after[kind],
                    'change_details': _('%s requires re-review after punch correction. Previous %s: %.2f; new calculated proposal: %.2f. Previous reviewer: %s. Reason: %s',
                        kind.title(), saved['state'], saved['amount'], after[kind]['amount'], saved['reviewer'] or '-', reason)})
                values = {kind + '_state': 'submitted', kind + '_re_review_required': True,
                          kind + '_hours': hours, kind + '_detected_hours': hours,
                          kind + '_amount': 0, kind + '_calculation_type': False, kind + '_rate': 0}
                if kind == 'fine':
                    values['fine_review_data'] = {}
                else:
                    values.update(overtime_template_id=False, overtime_slab_id=False,
                        overtime_resolved_rate=0, overtime_salary_basis_amount=0,
                        overtime_rate_override_reason=False)
                review.write(values)
        # Derived attendance review columns may have been cached before invalidation.
        self.env['hr.attendance'].invalidate_model([
            'bambus_fine_review_state', 'bambus_overtime_review_state',
            'bambus_approved_fine_hours', 'bambus_approved_fine_amount',
            'bambus_approved_overtime_hours', 'bambus_approved_overtime_amount'])

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('bambus_skip_recompute'):
            return super().create(vals_list)
        keys = set()
        defaults = self.default_get(['employee_id', 'check_in', 'check_out'])
        for vals in vals_list:
            keys |= self.new(dict(defaults, **vals))._revision_keys()
        snapshots = self._revision_before(keys)
        records = super().create(vals_list)
        records._revision_finish(keys | records._revision_keys(), snapshots, [], records._revision_punches(), 'created')
        return records

    def write(self, vals):
        if self.env.context.get('bambus_skip_recompute') or not {'check_in', 'check_out', 'employee_id'} & vals.keys():
            return super().write(vals)
        keys = self._revision_keys()
        for att in self:
            keys |= self.new(dict(employee_id=vals.get('employee_id', att.employee_id.id),
                check_in=vals.get('check_in', att.check_in), check_out=vals.get('check_out', att.check_out)))._revision_keys()
        snapshots = self._revision_before(keys)
        previous = self._revision_punches()
        result = super().write(vals)
        self._revision_finish(keys | self._revision_keys(), snapshots, previous, self._revision_punches(), 'updated')
        return result

    def unlink(self):
        if self.env.context.get('bambus_skip_recompute'):
            return super().unlink()
        keys = self._revision_keys()
        snapshots = self._revision_before(keys)
        previous = self._revision_punches()
        result = super().unlink()
        self.env['hr.attendance']._revision_finish(keys, snapshots, previous, [], 'deleted')
        return result


class ReviewRevision(models.Model):
    _inherit = 'bambus.attendance.day.review'

    fine_re_review_required = fields.Boolean(readonly=True, copy=False)
    overtime_re_review_required = fields.Boolean(readonly=True, copy=False)

    def _revision_decision(self, kind):
        self.ensure_one()
        return {'state': self[kind + '_state'], 'hours': self[kind + '_hours'],
                'amount': self[kind + '_amount'], 'calculation_type': self[kind + '_calculation_type'],
                'rate': self[kind + '_rate'], 'note': self[kind + '_note'],
                'reviewer': self[kind + '_updated_by_id'].display_name,
                'reviewer_id': self[kind + '_updated_by_id'].id,
                'reviewed_on': fields.Datetime.to_string(self[kind + '_updated_on']) or False,
                'decisions': deepcopy(self.fine_review_data) if kind == 'fine' else {}}

    def write(self, vals):
        vals = dict(vals)
        for kind in ('fine', 'overtime'):
            if vals.get(kind + '_state') in ('approved', 'rejected'):
                vals[kind + '_re_review_required'] = False
        pending = {kind: {record.id: record._revision_decision(kind) for record in self
                          if record[kind + '_re_review_required']}
                   for kind in ('fine', 'overtime') if vals.get(kind + '_state') in ('approved', 'rejected')}
        result = super().write(vals)
        for kind, snapshots in pending.items():
            for record in self.filtered(lambda row: row.id in snapshots):
                before, after = snapshots[record.id], record._revision_decision(kind)
                self.env['bambus.hr.attendance.time.audit'].sudo().create({
                    'employee_id': record.employee_id.id, 'date': record.date, 'adjustment_type': kind,
                    'previous_hours': before['hours'], 'adjusted_hours': after['hours'],
                    'updated_by_id': self.env.uid, 'previous_review': before, 'current_proposal': after,
                    'change_details': _('%s re-review completed: %s; amount %.2f. Note: %s',
                        kind.title(), after['state'], after['amount'], after['note'] or '-')})
        return result


class RevisionAudit(models.Model):
    _inherit = 'bambus.hr.attendance.time.audit'

    previous_review = fields.Json(readonly=True, copy=False)
    current_proposal = fields.Json(readonly=True, copy=False)
    punch_changes = fields.Json(readonly=True, copy=False)
    change_details = fields.Text(readonly=True)

    def write(self, vals):
        raise UserError(_('Attendance audit entries cannot be edited. Record a new correction instead.'))

    def unlink(self):
        raise UserError(_('Attendance audit entries cannot be deleted.'))


class RevisionPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_compute_sheet(self):
        for slip in self.filtered(lambda item: item.state in ('draft', 'verify')):
            pending = self.env['bambus.attendance.day.review'].sudo().search([
                ('employee_id', '=', slip.employee_id.id), ('company_id', '=', slip.company_id.id),
                ('date', '>=', slip.date_from), ('date', '<=', slip.date_to), '|',
                ('fine_re_review_required', '=', True), ('overtime_re_review_required', '=', True)], limit=1)
            if pending:
                raise UserError(_('Review corrected attendance for %s on %s before recomputing or confirming this payslip.',
                                  slip.employee_id.name, pending.date))
        return super().action_compute_sheet()
