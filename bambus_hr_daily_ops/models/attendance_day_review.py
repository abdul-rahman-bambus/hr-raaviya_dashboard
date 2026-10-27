# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, time, timedelta
import pytz


class AttendanceDayReview(models.Model):
    _name = 'bambus.attendance.day.review'
    _description = 'Employee Attendance Decision'
    _order = "employee_id"

    company_id = fields.Many2one('res.company', required=True, index=True,
        default=lambda self: self.env.company)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    legacy_sheet_id = fields.Integer(readonly=True, copy=False)
    _sql_constraints = [('employee_date_company_unique',
        'unique(employee_id, date, company_id)', 'One review per employee, company and date is allowed.')]

    employee_id = fields.Many2one("hr.employee", required=True, index=True)
    department_id = fields.Many2one(related="employee_id.department_id", store=True, readonly=True)

    # Current attendance (never a stored time snapshot)
    attendance_id = fields.Many2one("hr.attendance", compute="_compute_current_day")
    check_in = fields.Datetime(string="Punch In", compute="_compute_current_day")
    check_out = fields.Datetime(string="Punch Out", compute="_compute_current_day")
    worked_hours = fields.Float(string="Worked Hours", compute="_compute_current_day")

    punched_in = fields.Boolean(compute="_compute_flags", store=False)
    punched_out = fields.Boolean(compute="_compute_flags", store=False)

    # Current Time Off
    leave_id = fields.Many2one("hr.leave", string="Leave", compute="_compute_current_day")
    leave_state = fields.Selection(selection=lambda self: self.env['hr.leave']._fields['state']._description_selection(self.env),
        string="Leave Status", compute="_compute_current_day")
    is_half_day_leave = fields.Boolean(string="Half Day Leave", compute="_compute_current_day")

    status = fields.Selection(
        [("present", "Present"), ("absent", "Absent"), ("leave", "Leave"), ("halfday", "Half Day")],
        default="absent",
        required=True,
        index=True,
    )
    attendance_status_manual = fields.Boolean(
        string="Attendance Status Set by HR",
        help="Distinguishes an explicit HR status from a line created only to review OT/Fine.",
    )

    # OT / Fine detected values and HR-saved final values.
    overtime_hours = fields.Float(string="OT Hours", digits=(16, 6))
    overtime_detected_hours = fields.Float(string="System OT Hours", digits=(16, 6), readonly=True)
    overtime_amount = fields.Monetary(string="OT Amount")
    overtime_state = fields.Selection(
        [("draft", "No Exception"), ("submitted", "Needs Review"), ("approved", "Updated"), ("rejected", "Excluded")],
        default="draft",
    )
    overtime_calculation_type = fields.Selection([
        ("fixed", "Fixed Amount"),
        ("fixed_hour", "Fixed Amount per Hour"),
        ("half_day", "Half Day"),
        ("full_day", "Full Day"),
        ("regularize", "Regularize"),
        ("salary_1", "1x Salary"),
        ("salary_1_5", "1.5x Salary"),
        ("salary_2", "2x Salary"),
    ], string="OT Calculation")
    overtime_rate = fields.Monetary(string="Applied OT Rate")
    overtime_resolved_rate = fields.Monetary(string="Resolved OT Rate", readonly=True)
    overtime_rate_override_reason = fields.Char(string="OT Rate Override Reason", readonly=True)
    overtime_template_id = fields.Many2one(
        "bambus.attendance.automation.template", string="OT Automation Template", readonly=True
    )
    overtime_salary_basis_amount = fields.Monetary(
        string="OT Salary Basis", readonly=True
    )
    overtime_slab_id = fields.Many2one(
        "bambus.attendance.overtime.rate.slab", string="OT Salary Slab", readonly=True
    )
    overtime_note = fields.Char()
    overtime_updated_by_id = fields.Many2one("res.users", readonly=True)
    overtime_updated_on = fields.Datetime(readonly=True)

    hourly_pay_detected_hours = fields.Float(string="Detected Payable Hours", digits=(16, 6))
    hourly_pay_hours = fields.Float(string="Payable Hours", digits=(16, 6))
    hourly_pay_amount = fields.Monetary(string="Hourly Pay Amount")
    hourly_pay_calculation_type = fields.Selection([
        ("fixed", "Fixed Amount"), ("fixed_hour", "Fixed Amount per Hour"),
        ("half_day", "Half Day"), ("full_day", "Full Day"),
        ("regularize", "Regularize"), ("salary_1", "1x Salary"),
        ("salary_1_5", "1.5x Salary"), ("salary_2", "2x Salary"),
    ], string="Hourly Pay Calculation")
    hourly_pay_rate = fields.Monetary(string="Hourly Pay Rate")
    hourly_pay_state = fields.Selection([
        ("draft", "Not Reviewed"), ("approved", "Updated"),
    ], default="draft")
    hourly_pay_note = fields.Char()
    hourly_pay_updated_by_id = fields.Many2one("res.users", readonly=True)
    hourly_pay_updated_on = fields.Datetime(readonly=True)

    fine_hours = fields.Float(string="Fine Hours", digits=(16, 6))
    fine_detected_hours = fields.Float(string="System Fine Hours", digits=(16, 6), readonly=True)
    fine_amount = fields.Monetary(string="Fine Amount")
    fine_state = fields.Selection(
        [("draft", "No Exception"), ("submitted", "Needs Review"), ("approved", "Updated"), ("rejected", "Excluded")],
        default="draft",
    )
    fine_calculation_type = fields.Selection([
        ("fixed", "Fixed Amount"),
        ("fixed_hour", "Fixed Amount per Hour"),
        ("half_day", "Half Day"),
        ("full_day", "Full Day"),
        ("regularize", "Regularize"),
        ("salary_minute", "Per Minute from Daily Salary"),
        ("salary_1", "1x Salary"),
        ("salary_1_5", "1.5x Salary"),
        ("salary_2", "2x Salary"),
    ], string="Fine Calculation")
    fine_rate = fields.Float(string="Applied Fine Rate", digits=(16, 6))
    fine_note = fields.Char()
    fine_updated_by_id = fields.Many2one("res.users", readonly=True)
    fine_updated_on = fields.Datetime(readonly=True)

    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", store=False)

    # Contract / wage type (for Hourly/Monthly grouping)
    contract_id = fields.Many2one("hr.contract", string="Contract", compute="_compute_contract", compute_sudo=True)
    # ---- Wage Type (from Contract) for grouping Hourly/Monthly ----
    wage_type_display = fields.Char(string="Wage Type", compute="_compute_wage_type", store=True, index=True)

    # ---- Screenshot-like chips ----
    status_short = fields.Char(compute="_compute_ui_chips", store=False)
    punch_in_display = fields.Char(compute="_compute_ui_chips", store=False)
    punch_out_display = fields.Char(compute="_compute_ui_chips", store=False)
    ot_display = fields.Char(compute="_compute_ui_chips", store=False)
    fine_display = fields.Char(compute="_compute_ui_chips", store=False)

    @api.depends("employee_id", "date")
    def _compute_wage_type(self):
        """Reads wage type from employee's current/open contract (Cybrosys payroll community style)."""
        Contract = self.env["hr.contract"].sudo()
        for rec in self:
            rec.wage_type_display = ""
            emp = rec.employee_id
            if not emp:
                continue

            # Try current contract first (if present), else find latest open contract
            contract = getattr(emp, "contract_id", False)
            if not contract:
                contract = Contract.search(
                    [("employee_id", "=", emp.id), ("state", "in", ["open", "draft"])],
                    order="date_start desc, id desc",
                    limit=1
                )

            if not contract:
                continue

            # Cybrosys payroll community usually has wage type in contract
            if "wage_type" in contract._fields:
                code = contract.wage_type
                label = dict(contract._fields["wage_type"].selection).get(code) if code else ""
                rec.wage_type_display = label or (code or "")
            else:
                # fallback
                rec.wage_type_display = _("Monthly")


    @api.constrains('employee_id', 'company_id')
    def _check_employee_company(self):
        for rec in self:
            if rec.employee_id.company_id != rec.company_id:
                raise ValidationError(_('The attendance decision must belong to the employee company.'))

    def _bambus_check_line_locked(self, vals=None):
        return True

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    def write(self, vals):
        # Preserve the legacy hook while allowing HR attendance maintenance
        self._bambus_check_line_locked(vals)
        return super().write(vals)

    def unlink(self):
        self._bambus_check_line_locked()
        return super().unlink()


    def _fmt_time_user(self, dt):
        """Convert UTC dt -> user TZ and format like 9:58 AM."""
        if not dt:
            return ""
        local = fields.Datetime.context_timestamp(self, dt)
        return local.strftime("%I:%M %p").lstrip("0")

    def _hours_to_hm(self, hours_float):
        mins = int(round((hours_float or 0.0) * 60))
        hh, mm = divmod(mins, 60)
        return f"{hh:d}:{mm:02d}"

    @api.depends("status", "check_in", "check_out", "overtime_hours", "fine_hours")
    def _compute_ui_chips(self):
        for rec in self:
            rec.status_short = {"present": "P", "absent": "A", "leave": "L", "halfday": "HD"}.get(rec.status, "")

            rec.punch_in_display = ""
            rec.punch_out_display = ""
            if rec.check_in:
                rec.punch_in_display = f"PI | {rec._fmt_time_user(rec.check_in)}"
            if rec.check_out:
                rec.punch_out_display = f"PO | {rec._fmt_time_user(rec.check_out)}"

            rec.ot_display = ""
            if (rec.overtime_hours or 0.0) > 0:
                rec.ot_display = f"OT | +{rec._hours_to_hm(rec.overtime_hours)} Hrs"

            rec.fine_display = ""
            if (rec.fine_hours or 0.0) > 0:
                rec.fine_display = f"F | {rec._hours_to_hm(rec.fine_hours)} Hrs"



    @api.depends("check_in", "check_out")
    def _compute_flags(self):
        for rec in self:
            rec.punched_in = bool(rec.check_in)
            rec.punched_out = bool(rec.check_out)

    def _day_bounds_utc(self, day):
        start_dt = datetime.combine(day, time.min)
        end_dt = start_dt + timedelta(days=1)
        return start_dt, end_dt

    @api.depends('employee_id', 'date', 'company_id')
    def _compute_contract(self):
        for rec in self:
            rec.contract_id = self.env['hr.contract'].search([
                ('employee_id', '=', rec.employee_id.id), ('company_id', '=', rec.company_id.id),
                ('state', 'in', ['draft', 'open']), ('date_start', '<=', rec.date),
                '|', ('date_end', '=', False), ('date_end', '>=', rec.date),
            ], order='date_start desc, id desc', limit=1) if rec.employee_id and rec.date else False

    @api.depends('employee_id', 'date', 'company_id',
        'employee_id.attendance_ids.check_in', 'employee_id.attendance_ids.check_out',
        'employee_id.attendance_ids.worked_hours')
    def _compute_current_day(self):
        for rec in self:
            punches = rec._review_attendances() if rec.employee_id and rec.date else self.env['hr.attendance']
            rec.attendance_id = punches[:1]
            rec.check_in = min(punches.mapped('check_in')) if punches else False
            outs = punches.filtered('check_out').mapped('check_out')
            rec.check_out = max(outs) if outs else False
            rec.worked_hours = sum(punches.mapped('worked_hours'))
            leave = self.env['hr.leave'].search([
                ('employee_id', '=', rec.employee_id.id), ('state', 'in', ['confirm', 'validate1', 'validate']),
                ('request_date_from', '<=', rec.date), ('request_date_to', '>=', rec.date)
            ], order='id desc', limit=1) if rec.employee_id and rec.date else self.env['hr.leave']
            rec.leave_id = leave
            rec.leave_state = leave.state if leave else False
            rec.is_half_day_leave = bool(leave and leave.request_unit_half)

    def _compute_day_data(self):
        """Refresh live proposals; saved approval amounts are never repriced."""
        self.invalidate_recordset(['check_in', 'check_out', 'worked_hours', 'attendance_id',
            'contract_id', 'leave_id', 'is_half_day_leave'])
        for rec in self:
            punches = rec._review_attendances()
            for kind, hours in [('overtime', sum(punches.mapped('overtime_hours'))),
                    ('fine', sum(punches.mapped('bambus_fine_hours')))]:
                if rec[kind + '_state'] not in ('approved', 'rejected'):
                    values = {name: hours for name in (kind + '_hours', kind + '_detected_hours')
                              if rec[name] != hours}
                    if values:
                        rec.write(values)
        return True

    def action_refresh(self):
        self._compute_day_data()
        return True

    # --- Buttons (open popup wizards) ---
    def action_edit_attendance(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Punches"),
            "res_model": "bambus.hr.attendance.multi.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_line_id": self.id},
        }



    def action_edit_overtime(self):
        self.ensure_one()
        form_view = self.env.ref(
            "bambus_hr_daily_ops.view_bambus_hr_overtime_wizard"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Edit Overtime"),
            "res_model": "bambus.hr.overtime.wizard",
            "view_mode": "form",
            "views": [(form_view.id, "form")],
            "target": "new",
            "context": {"default_line_id": self.id},
        }

    def action_edit_fine(self):
        self.ensure_one()
        form_view = self.env.ref(
            "bambus_hr_daily_ops.view_bambus_hr_fine_wizard"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Fine"),
            "res_model": "bambus.hr.fine.wizard",
            "view_mode": "form",
            "views": [(form_view.id, "form")],
            "target": "new",
            "context": {"default_line_id": self.id},
        }

    def action_edit_hourly_pay(self):
        self.ensure_one()
        form_view = self.env.ref("bambus_hr_daily_ops.view_bambus_hr_hourly_pay_wizard")
        return {
            "type": "ir.actions.act_window",
            "name": _("Hourly Pay"),
            "res_model": "bambus.hr.hourly.pay.wizard",
            "view_mode": "form",
            "views": [(form_view.id, "form")],
            "target": "new",
            "context": {"default_line_id": self.id},
        }

    def action_mark_halfday_leave(self):
        self.ensure_one()
        return self.env['bambus.attendance.dashboard'].prepare_half_day_leave(self.employee_id.id, self.date)

    def action_mark_full_leave(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mark Leave"),
            "res_model": "bambus.hr.leave.quick.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_line_id": self.id, "default_leave_unit": "full"},
        }

    def action_force_absent(self):
        self.ensure_one()
        self.status = "absent"
        return True


class BambusHrAttendanceTimeAudit(models.Model):
    _name = "bambus.hr.attendance.time.audit"
    _description = "HR Attendance Time Update"
    _order = "create_date desc, id desc"

    employee_id = fields.Many2one("hr.employee", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="employee_id.company_id", store=True, index=True)
    date = fields.Date(required=True, index=True)
    adjustment_type = fields.Selection([
        ("attendance", "Attendance time adjusted"),
        ("overtime", "Overtime adjusted"),
        ("fine", "Late / Fine adjusted"),
        ("hourly_pay", "Hourly pay adjusted"),
    ], required=True, default="attendance", index=True)
    adjusted_hours = fields.Float(digits=(16, 6))
    exception_decisions = fields.Json(readonly=True, copy=False)
    previous_fine_review = fields.Json(readonly=True, copy=False)
    previous_hours = fields.Float(digits=(16, 6))
    previous_check_in = fields.Datetime(string="Previous Check In")
    previous_check_out = fields.Datetime(string="Previous Check Out")
    check_in = fields.Datetime(string="Adjusted Check In")
    check_out = fields.Datetime(string="Adjusted Check Out")
    updated_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True
    )
