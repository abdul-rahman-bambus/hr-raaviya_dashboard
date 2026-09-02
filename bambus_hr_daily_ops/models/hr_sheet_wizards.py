# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, time, timedelta
import pytz


class BambusHrAttendanceMultiWizard(models.TransientModel):
    _name = "bambus.hr.attendance.multi.wizard"
    _description = "Edit Daily Punches"

    line_id = fields.Many2one("bambus.hr.attendance.sheet.line", required=True)
    employee_id = fields.Many2one(related="line_id.employee_id", readonly=True)
    date = fields.Date(related="line_id.date", readonly=True)

    line_ids = fields.One2many("bambus.hr.attendance.multi.wizard.line", "wizard_id", string="Punches")
    original_attendance_ids = fields.Many2many("hr.attendance", string="Original", readonly=True)
    delete_removed = fields.Boolean(string="Delete removed punches", default=True)

    total_worked_hours = fields.Float(string="Worked Hours", compute="_compute_totals", store=False)
    total_ot_amount = fields.Monetary(string="OT Amount", currency_field="currency_id", compute="_compute_totals", store=False)
    total_fine_amount = fields.Monetary(string="Fine Amount", currency_field="currency_id", compute="_compute_totals", store=False)
    currency_id = fields.Many2one("res.currency", related="line_id.currency_id", readonly=True)

    timeline_html = fields.Html(string="Timeline", compute="_compute_timeline_html", sanitize=False, store=False)

    def _day_bounds_utc(self, day):
        tzname = self.env.user.tz or "UTC"
        tz = pytz.timezone(tzname)
        start_local = tz.localize(datetime.combine(day, time.min))
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        return start_utc, end_utc

    @api.depends("line_ids.check_in", "line_ids.check_out", "line_ids.attendance_id")
    def _compute_totals(self):
        for wiz in self:
            worked = 0.0
            for wl in wiz.line_ids:
                if wl.attendance_id and wl.attendance_id.worked_hours:
                    worked += wl.attendance_id.worked_hours
                elif wl.check_in and wl.check_out:
                    delta = wl.check_out - wl.check_in
                    worked += (delta.total_seconds() / 3600.0)
            wiz.total_worked_hours = worked

            wiz.total_ot_amount = wiz.line_id.overtime_amount or 0.0
            wiz.total_fine_amount = wiz.line_id.fine_amount or 0.0

    def _img_url(self, att_id, field_name):
        return f"/web/image/hr.attendance/{att_id}/{field_name}"

    def _fmt_time_user(self, dt):
        if not dt:
            return ""
        local = fields.Datetime.context_timestamp(self, dt)
        return local.strftime("%I:%M %p").lstrip("0")

    @api.depends("line_ids.check_in", "line_ids.check_out", "line_ids.attendance_id")
    def _compute_timeline_html(self):
        Attendance = self.env["hr.attendance"].sudo()
        has_ci = "recognized_face_checkin" in Attendance._fields
        has_co = "recognized_face_checkout" in Attendance._fields

        def _face_html(wiz, att_id, field_name, side="right"):
            src = wiz._img_url(att_id, field_name)
            side_cls = "bambus-pop-left" if side == "left" else ""
            return f"""
                <span class="bambus-face-wrap {side_cls}">
                  <img class="bambus-face-thumb" src="{src}" alt="{field_name}"/>
                  <span class="bambus-face-pop"><img src="{src}" alt="{field_name}"/></span>
                </span>
                """

        def _fmt_hhmm(hours):
            """float hours -> HH:MM (rounded to nearest minute)"""
            try:
                h = float(hours or 0.0)
            except Exception:
                h = 0.0
            total_min = int(round(h * 60.0))
            hh = total_min // 60
            mm = total_min % 60
            return f"{hh:02d}:{mm:02d}"

        def _fmt_money(amount, currency):
            """amount -> with currency symbol based on currency.position"""
            try:
                amt = float(amount or 0.0)
            except Exception:
                amt = 0.0
            amt_str = f"{amt:,.2f}"
            if not currency:
                return amt_str
            sym = currency.symbol or ""
            pos = (currency.position or "before").lower()
            return f"{amt_str} {sym}" if pos == "after" else f"{sym} {amt_str}"



        for wiz in self:
            lines = sorted(wiz.line_ids, key=lambda l: (l.check_in or datetime.min, l.id))
            
            # currency for symbol
            currency = False
            if "currency_id" in wiz._fields and wiz.currency_id:
                currency = wiz.currency_id
            else:
                currency = wiz.env.company.currency_id

            worked_txt = _fmt_hhmm(wiz.total_worked_hours)

            # OT hours: use wizard field if exists, else sum from attendances
            total_ot_hours = getattr(wiz, "total_ot_hours", None)
            if total_ot_hours is None:
                total_ot_hours = sum((l.attendance_id.overtime_hours or 0.0) for l in lines if l.attendance_id)
            ot_hours_txt = _fmt_hhmm(total_ot_hours)

            # Fine hours: use wizard field if exists, else sum fine hours from attendances
            total_fine_hours = getattr(wiz, "total_fine_hours", None)
            if total_fine_hours is None:
                total_fine_hours = sum((l.attendance_id.bambus_fine_hours or 0.0) for l in lines if l.attendance_id)
            fine_hours_txt = _fmt_hhmm(total_fine_hours)

            ot_amt_txt = _fmt_money(wiz.total_ot_amount, currency)
            fine_amt_txt = _fmt_money(wiz.total_fine_amount, currency)

            rows = []

            for idx, wl in enumerate(lines, start=1):
                ci = wl.check_in
                co = wl.check_out
                ci_txt = wiz._fmt_time_user(ci) if ci else "-"
                co_txt = wiz._fmt_time_user(co) if co else "-"

                ci_img = ""
                co_img = ""
                if wl.attendance_id:
                    if has_ci:
                        ci_img = _face_html(wiz, wl.attendance_id.id, "recognized_face_checkin", side="right")
                    if has_co:
                        co_img = _face_html(wiz, wl.attendance_id.id, "recognized_face_checkout", side="left")


                # Alternate rows flipped (helps right edge without JS)
                # flip_cls = "bambus-flip" if (idx % 2 == 0) else ""

                rows.append(f"""
                    <div class="bambus-timeline-row" style="
                      display:flex;align-items:center;justify-content:space-between;
                      padding:10px 0;border-bottom:1px solid #eee;">
                      <div style="display:flex;align-items:center;gap:14px;min-width:45%;">
                        <span style="background:#198754;color:#fff;font-weight:600;font-size:12px;
                          padding:3px 10px;border-radius:999px;">PI</span>
                        <span style="font-weight:600;">{ci_txt}</span>
                        <span>{ci_img}</span>
                      </div>

                      <div style="color:#666;padding:0 10px;">→</div>

                      <div style="display:flex;align-items:center;gap:14px;justify-content:flex-end;min-width:45%;">
                        <span style="background:#0d6efd;color:#fff;font-weight:600;font-size:12px;
                          padding:3px 10px;border-radius:999px;">PO</span>
                        <span style="font-weight:600;">{co_txt}</span>
                        <span>{co_img}</span>
                      </div>
                    </div>
                    """)

            body = '<div style="color:#666;">No punches for this day.</div>' if not rows else "".join(rows)

            wiz.timeline_html = f"""
                    <div style="padding:8px;">
                      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
                        <span style="background:#0dcaf0;color:#111;padding:4px 10px;border-radius:999px;font-weight:600;">
                          Worked: {worked_txt}h
                        </span>
                        <span style="background:#ffc107;color:#111;padding:4px 10px;border-radius:999px;font-weight:600;">
                          OT: {ot_hours_txt} | {ot_amt_txt}
                        </span>
                        <span style="background:#dc3545;color:#fff;padding:4px 10px;border-radius:999px;font-weight:600;">
                          Fine: {fine_hours_txt} | {fine_amt_txt}
                        </span>

                      </div>

                      <div style="border:1px solid #ddd;border-radius:12px;padding:10px;max-width:760px;margin:0 auto;">
                        {body}
                      </div>
                    </div>
                    """

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line = self.env["bambus.hr.attendance.sheet.line"].browse(self.env.context.get("default_line_id"))
        if not line or not line.exists():
            return res

        res["line_id"] = line.id

        Attendance = self.env["hr.attendance"].sudo()
        start_utc, end_utc = self._day_bounds_utc(line.date)

        atts = Attendance.search([
            ("employee_id", "=", line.employee_id.id),
            ("check_in", "<", fields.Datetime.to_string(end_utc)),
            "|",
                ("check_out", "=", False),
                ("check_out", ">", fields.Datetime.to_string(start_utc)),
        ], order="check_in asc")

        res["original_attendance_ids"] = [(6, 0, atts.ids)]
        res["line_ids"] = [(0, 0, {
            "attendance_id": a.id,
            "check_in": a.check_in,
            "check_out": a.check_out,
        }) for a in atts]

        return res

    def action_apply(self):
        self.ensure_one()
        Attendance = self.env["hr.attendance"].sudo()
        emp = self.employee_id

        # ✅ IMPORTANT: make sure latest edits on wizard lines are persisted before we read them
        self.flush_recordset(["line_ids"])
        self.line_ids.flush_model(["attendance_id", "check_in", "check_out"])

        for wl in self.line_ids:
            if not wl.check_in:
                raise ValidationError(_("Each row must have a Punch In."))
            if wl.check_out and wl.check_out < wl.check_in:
                raise ValidationError(_("Punch Out must be after Punch In."))

        kept_ids = set()
        for wl in self.line_ids:
            if wl.attendance_id and wl.attendance_id.id:
                att = Attendance.browse(wl.attendance_id.id)  # Attendance is sudo()
                # ✅ write only what we need (keeps triggers clean)
                vals = {
                    "check_in": wl.check_in,
                    "check_out": wl.check_out or False,
                }
                att.write(vals)
                kept_ids.add(att.id)
            else:
                new_att = Attendance.create({
                    "employee_id": emp.id,
                    "check_in": wl.check_in,
                    "check_out": wl.check_out or False,
                })
                kept_ids.add(new_att.id)

        if self.delete_removed:
            original_ids = set(self.original_attendance_ids.ids)
            removed_ids = list(original_ids - kept_ids)
            if removed_ids:
                Attendance.browse(removed_ids).unlink()

        # refresh snapshot on sheet line
        self.line_id._compute_day_data()
        return {"type": "ir.actions.client", "tag": "reload"}




class BambusHrAttendanceMultiWizardLine(models.TransientModel):
    _name = "bambus.hr.attendance.multi.wizard.line"
    _description = "Edit Daily Punches Line"
    _order = "check_in asc, id asc"

    wizard_id = fields.Many2one("bambus.hr.attendance.multi.wizard", required=True, ondelete="cascade")
    attendance_id = fields.Many2one("hr.attendance", string="Attendance")
    check_in = fields.Datetime()
    check_out = fields.Datetime()
    # Face images from hr.attendance (your custom fields)
    recognized_face_checkin = fields.Binary(related="attendance_id.recognized_face_checkin", readonly=True)
    recognized_face_checkout = fields.Binary(related="attendance_id.recognized_face_checkout", readonly=True)

    @api.constrains("check_in", "check_out")
    def _check_times(self):
        for r in self:
            if r.check_in and r.check_out and r.check_out < r.check_in:
                raise UserError(_("Check Out cannot be earlier than Check In."))

    def action_open_attendance(self):
        self.ensure_one()
        if not self.attendance_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Attendance"),
            "res_model": "hr.attendance",
            "res_id": self.attendance_id.id,
            "view_mode": "form",
            "target": "current",
        }


class BambusHrOvertimeWizard(models.TransientModel):
    _name = "bambus.hr.overtime.wizard"
    _description = "Edit Overtime"

    line_id = fields.Many2one("bambus.hr.attendance.sheet.line", required=True, ondelete="cascade")
    employee_id = fields.Many2one(related="line_id.employee_id", readonly=True)
    date = fields.Date(related="line_id.date", readonly=True)

    overtime_hours = fields.Float(digits=(16, 2))
    overtime_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="line_id.currency_id", readonly=True)
    note = fields.Char()
    send_sms = fields.Boolean()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line = self.env["bambus.hr.attendance.sheet.line"].browse(self.env.context.get("default_line_id"))
        if line and line.exists():
            res.update({
                "line_id": line.id,
                "overtime_hours": line.overtime_hours,
                "overtime_amount": line.overtime_amount,
            })
        return res

    def action_apply(self):
        self.ensure_one()
        vals = {
            "overtime_hours": self.overtime_hours,
            "overtime_amount": self.overtime_amount,
            "overtime_state": "submitted" if (self.overtime_hours or 0.0) > 0 or (self.overtime_amount or 0.0) > 0 else "draft",
        }
        self.line_id.sudo().write(vals)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_approve(self):
        self.ensure_one()
        vals = {
            "overtime_hours": self.overtime_hours,
            "overtime_amount": self.overtime_amount,
            "overtime_state": "approved",
        }
        self.line_id.sudo().write(vals)
        return {"type": "ir.actions.client", "tag": "reload"}


class BambusHrFineWizard(models.TransientModel):
    _name = "bambus.hr.fine.wizard"
    _description = "Fine"

    line_id = fields.Many2one("bambus.hr.attendance.sheet.line", required=True, ondelete="cascade")
    employee_id = fields.Many2one(related="line_id.employee_id", readonly=True)
    date = fields.Date(related="line_id.date", readonly=True)

    fine_hours = fields.Float(digits=(16, 2))
    fine_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="line_id.currency_id", readonly=True)
    reason = fields.Char()
    send_sms = fields.Boolean()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line = self.env["bambus.hr.attendance.sheet.line"].browse(self.env.context.get("default_line_id"))
        if line and line.exists():
            res.update({
                "line_id": line.id,
                "fine_hours": line.fine_hours,
                "fine_amount": line.fine_amount,
            })
        return res

    def action_apply(self):
        self.ensure_one()
        vals = {
            "fine_hours": self.fine_hours,
            "fine_amount": self.fine_amount,
            "fine_state": "submitted" if (self.fine_hours or 0.0) > 0 or (self.fine_amount or 0.0) > 0 else "draft",
        }
        self.line_id.sudo().write(vals)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_approve(self):
        self.ensure_one()
        vals = {
            "fine_hours": self.fine_hours,
            "fine_amount": self.fine_amount,
            "fine_state": "approved",
        }
        self.line_id.sudo().write(vals)
        return {"type": "ir.actions.client", "tag": "reload"}


class BambusHrLeaveQuickWizard(models.TransientModel):
    _name = "bambus.hr.leave.quick.wizard"
    _description = "Quick Leave"

    line_id = fields.Many2one("bambus.hr.attendance.sheet.line", required=True, ondelete="cascade")
    employee_id = fields.Many2one(related="line_id.employee_id", readonly=True)
    date = fields.Date(related="line_id.date", readonly=True)

    leave_id = fields.Many2one("hr.leave", string="Existing Leave", readonly=True)

    leave_type_id = fields.Many2one("hr.leave.type", required=True)
    leave_unit = fields.Selection([("full", "Full Day"), ("half", "Half Day")], default="full", required=True)
    leave_period = fields.Selection([("am", "Morning"), ("pm", "Afternoon")], default="am")
    description = fields.Char()

    request_date_from = fields.Date(required=True)
    request_date_to = fields.Date(required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line = self.env["bambus.hr.attendance.sheet.line"].browse(self.env.context.get("default_line_id"))
        if not line or not line.exists():
            return res

        res["line_id"] = line.id

        Leave = self.env["hr.leave"].sudo()
        leave = Leave.search([
            ("employee_id", "=", line.employee_id.id),
            ("state", "!=", "refuse"),
            ("request_date_from", "<=", line.date),
            ("request_date_to", ">=", line.date),
        ], order="id desc", limit=1)

        if leave:
            res["leave_id"] = leave.id
            res["leave_type_id"] = leave.holiday_status_id.id
            res["request_date_from"] = leave.request_date_from
            res["request_date_to"] = leave.request_date_to
            res["description"] = leave.name or ""

            if "request_unit_half" in leave._fields and leave.request_unit_half:
                res["leave_unit"] = "half"
                if "request_date_from_period" in leave._fields and leave.request_date_from_period:
                    res["leave_period"] = leave.request_date_from_period
            else:
                res["leave_unit"] = "full"
        else:
            res["request_date_from"] = line.date
            res["request_date_to"] = line.date

        # Support button default (Half/Full)
        if self.env.context.get("default_leave_unit"):
            res["leave_unit"] = self.env.context["default_leave_unit"]

        return res

    def _validate_dates(self):
        for wiz in self:
            if wiz.request_date_to and wiz.request_date_from and wiz.request_date_to < wiz.request_date_from:
                raise ValidationError(_("To date must be >= From date."))

    def action_apply(self):
        self.ensure_one()
        self._validate_dates()

        line = self.line_id.sudo()
        Leave = self.env["hr.leave"].sudo()

        vals = {
            "employee_id": line.employee_id.id,
            "holiday_status_id": self.leave_type_id.id,
            "request_date_from": self.request_date_from,
            "request_date_to": self.request_date_to,
            "name": self.description or _("Leave"),
        }

        # Half-day fields only if available in your version/config
        if self.leave_unit == "half":
            if "request_unit_half" in Leave._fields:
                vals["request_unit_half"] = True
            if "request_date_from_period" in Leave._fields:
                vals["request_date_from_period"] = self.leave_period
            if "request_date_to_period" in Leave._fields:
                vals["request_date_to_period"] = self.leave_period
        else:
            if "request_unit_half" in Leave._fields:
                vals["request_unit_half"] = False

        # UPDATE existing leave if present, else CREATE new
        if self.leave_id:
            leave = self.leave_id.sudo()
            leave.write(vals)
        else:
            leave = Leave.create(vals)
            # set on wizard (so Delete becomes available immediately if you keep dialog open)
            self.leave_id = leave.id

        # Auto workflow: confirm/approve/validate if user has rights
        # (Odoo uses different methods depending on version/config)
        try:
            if hasattr(leave, "action_confirm"):
                leave.action_confirm()
            if hasattr(leave, "action_approve"):
                leave.action_approve()
            if hasattr(leave, "action_validate"):
                leave.action_validate()
        except Exception:
            # if permissions/state block, it's okay—leave stays as draft/confirm
            pass

        line._compute_day_data()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_delete(self):
        self.ensure_one()
        if not self.leave_id:
            return {"type": "ir.actions.client", "tag": "reload"}

        leave = self.leave_id.sudo()

        # If it’s validated, Odoo may require refusing first depending on rules/rights
        try:
            if hasattr(leave, "action_refuse") and leave.state != "refuse":
                leave.action_refuse()
            if hasattr(leave, "action_reset_confirm"):
                leave.action_reset_confirm()
        except Exception:
            pass

        leave.unlink()
        self.line_id._compute_day_data()
        return {"type": "ir.actions.client", "tag": "reload"}
