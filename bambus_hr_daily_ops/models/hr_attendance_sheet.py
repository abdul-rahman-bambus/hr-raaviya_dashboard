# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, time, timedelta


class BambusHrAttendanceSheet(models.Model):
    _name = "bambus.hr.attendance.sheet"
    _description = "Daily Attendance Sheet"
    _order = "date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    department_id = fields.Many2one("hr.department", string="Department (optional)")

    line_ids = fields.One2many("bambus.hr.attendance.sheet.line", "sheet_id", string="Employees")

    # KPI fields (top summary)
    total_staff = fields.Integer(compute="_compute_kpis", store=False)
    present_count = fields.Integer(compute="_compute_kpis", store=False)
    absent_count = fields.Integer(compute="_compute_kpis", store=False)
    halfday_count = fields.Integer(compute="_compute_kpis", store=False)
    leave_count = fields.Integer(compute="_compute_kpis", store=False)
    punched_in_count = fields.Integer(compute="_compute_kpis", store=False)
    punched_out_count = fields.Integer(compute="_compute_kpis", store=False)
    overtime_hours_total = fields.Float(compute="_compute_kpis", store=False)
    fine_hours_total = fields.Float(compute="_compute_kpis", store=False)
    employee_search = fields.Char(string="Search Employee")
    kpi_filter = fields.Selection([
        ("all", "All"),
        ("present", "Present"),
        ("absent", "Absent"),
        ("halfday", "Half Day"),
        ("leave", "Leave"),
        ("punched_in", "Punched In"),
        ("punched_out", "Punched Out"),
        ("ot", "Overtime"),
        ("fine", "Fine"),
        ], default="all", string="Quick Filter")
    line_ids_view = fields.Many2many(
        "bambus.hr.attendance.sheet.line",
        compute="_compute_line_ids_view",
        store=False,
        string="Staff (Filtered)"
    )

    # -----------------
    # Approval workflow
    # -----------------
    state = fields.Selection([
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
    ], default="draft", required=True, index=True)

    submitted_by_id = fields.Many2one("res.users", readonly=True)
    submitted_on = fields.Datetime(readonly=True)
    approved_by_id = fields.Many2one("res.users", readonly=True)
    approved_on = fields.Datetime(readonly=True)

    _sql_constraints = [
    ('uniq_sheet_date_company',
     'unique(company_id, date)',
     'Attendance sheet already exists for this date (per company).')
]

    @api.model
    def get_attendance_dashboard(self, selected_date=None):
        """Read metrics from the existing daily sheet; never create or refresh it."""
        day = fields.Date.to_date(selected_date) if selected_date else fields.Date.context_today(self)
        company = self.env.company
        sheet = self.search([
            ("date", "=", day),
            ("company_id", "=", company.id),
        ], limit=1)
        # The sheet search above enforces the user's company/record rules.  Once
        # that parent is authorized, read its lines in the parent context so a
        # rule inherited from another HR add-on cannot silently hide every line
        # and turn valid historical totals into zeroes.
        lines = sheet.sudo().line_ids if sheet else self.env["bambus.hr.attendance.sheet.line"]
        employee_ids = lines.employee_id.ids
        upcoming_leaves = self.env["hr.leave"].search([
            ("employee_id", "in", employee_ids),
            ("state", "=", "validate"),
            ("request_date_from", ">", day),
        ])
        present_lines = lines.filtered(lambda line: line.status == "present")
        absent_lines = lines.filtered(lambda line: line.status == "absent")
        halfday_lines = lines.filtered(lambda line: line.status == "halfday")
        leave_lines = lines.filtered(lambda line: line.status == "leave")
        return {
            "date": fields.Date.to_string(day),
            "company": company.display_name,
            "has_sheet": bool(sheet),
            "sheet_id": sheet.id or False,
            "line_count": len(lines),
            "metrics": {
                "total": len(lines),
                "present": len(present_lines),
                "absent": len(absent_lines),
                "halfday": len(halfday_lines),
                "leave": len(leave_lines),
                "punched_in": len(lines.filtered("check_in")),
                "punched_out": len(lines.filtered("check_out")),
                "not_marked": len(absent_lines.filtered(lambda line: not line.check_in)),
                "upcoming_leaves": len(set(upcoming_leaves.employee_id.ids)),
                "overtime": round(sum(lines.mapped("overtime_hours")), 2),
                "fine": round(sum(lines.mapped("fine_hours")), 2),
                "fine_amount": round(sum(lines.mapped("fine_amount")), 2),
                "on_duty": 0,
                "upcoming_on_duty": 0,
                "deactivated": len(lines.filtered(lambda line: not line.employee_id.active)),
                "daily_work_entries": len(lines.filtered("attendance_id")),
            },
        }


    def _filtered_lines(self):
        self.ensure_one()
        lines = self.line_ids

        f = self.kpi_filter or "all"
        if f == "present":
            lines = lines.filtered(lambda l: l.status == "present")
        elif f == "absent":
            lines = lines.filtered(lambda l: l.status == "absent")
        elif f == "halfday":
            lines = lines.filtered(lambda l: l.status == "halfday")
        elif f == "leave":
            lines = lines.filtered(lambda l: l.status in ("leave", "halfday"))
        elif f == "punched_in":
            lines = lines.filtered(lambda l: bool(l.check_in))
        elif f == "punched_out":
            lines = lines.filtered(lambda l: bool(l.check_out))
        elif f == "ot":
            lines = lines.filtered(lambda l: (l.overtime_hours or 0) > 0)
        elif f == "fine":
            lines = lines.filtered(lambda l: (l.fine_hours or 0) > 0)

        s = (self.employee_search or "").strip().lower()
        if s:
            lines = lines.filtered(lambda l: s in ((l.employee_id.name or "").lower()))

        return lines

    @api.depends(
        "kpi_filter", "employee_search",
        "line_ids.status", "line_ids.check_in", "line_ids.check_out",
        "line_ids.overtime_hours", "line_ids.fine_hours",
        "line_ids.employee_id",
    )
    def _compute_line_ids_view(self):
        for sheet in self:
            sheet.line_ids_view = sheet._filtered_lines()

    @api.onchange("kpi_filter", "employee_search")
    def _onchange_filters(self):
        for sheet in self:
            sheet.line_ids_view = sheet._filtered_lines()

    def action_clear_employee_search(self):
        self.ensure_one()
        self.employee_search = False
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_set_kpi_filter(self):
        self.ensure_one()
        self.kpi_filter = self.env.context.get("kpi") or "all"
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_clear_kpi_filter(self):
        self.ensure_one()
        self.kpi_filter = "all"
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_submit(self):
        for sheet in self:
            if sheet.state != "draft":
                continue
            sheet.write({
                "state": "submitted",
                "submitted_by_id": self.env.user.id,
                "submitted_on": fields.Datetime.now(),
            })
        return True

    def action_approve(self):
        # keep strict: only HR Manager can approve
        if not self.env.user.has_group("hr.group_hr_manager"):
            raise UserError(_("Only HR Manager can approve the sheet."))
        for sheet in self:
            if sheet.state != "submitted":
                continue
            sheet.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_on": fields.Datetime.now(),
            })
        return True

    def _bambus_check_sheet_locked(self, vals=None):
        """Lock edits after approval, but allow filter fields."""
        vals = vals or {}
        allowed_when_approved = {"kpi_filter", "employee_search"}  # allow viewing filters
        for sheet in self:
            if sheet.state == "approved":
                illegal = set(vals.keys()) - allowed_when_approved
                if illegal:
                    raise UserError(_("This Attendance Sheet is approved and cannot be edited."))

    def write(self, vals):
        self._bambus_check_sheet_locked(vals)
        return super().write(vals)

    def unlink(self):
        for sheet in self:
            if sheet.state == "approved":
                raise UserError(_("Approved sheets cannot be deleted."))
        return super().unlink()


    @api.depends("date", "department_id")
    def _compute_name(self):
        for rec in self:
            rec.name = f"Attendance Sheet - {rec.date}"

    def _day_bounds_utc(self, day):
        # Simple UTC day bounds (ok for internal usage; if you want timezone-perfect, we’ll adjust)
        start_dt = datetime.combine(day, time.min)
        end_dt = start_dt + timedelta(days=1)
        return start_dt, end_dt

    def action_generate_lines(self):
        """Create/refresh lines for employees for that date."""
        for sheet in self:
            if sheet.state == "approved":
                raise UserError(_("Approved sheet cannot be regenerated."))
            if not sheet.date:
                raise UserError(_("Select a date."))

            domain = [("active", "=", True)]
            # company filter (multi-company)
            domain += [("company_id", "=", sheet.company_id.id)]
            if sheet.department_id:
                domain += [("department_id", "=", sheet.department_id.id)]

            employees = self.env["hr.employee"].search(domain, order="name asc")
            if not employees:
                raise UserError(_("No employees found for this company/department."))

            # keep existing lines if already created
            existing = {l.employee_id.id: l for l in sheet.line_ids}
            vals_list = []
            for emp in employees:
                if emp.id in existing:
                    continue
                vals_list.append({
                    "sheet_id": sheet.id,
                    "employee_id": emp.id,
                    "date": sheet.date,
                })
            if vals_list:
                self.env["bambus.hr.attendance.sheet.line"].create(vals_list)

            # refresh computed values on lines (attendance/leave status)
            sheet.line_ids._compute_day_data()
        return True

    @api.depends("line_ids.status", "line_ids.punched_in", "line_ids.punched_out",
                 "line_ids.overtime_hours", "line_ids.fine_hours",
                 "line_ids.leave_state")
    def _compute_kpis(self):
        for sheet in self:
            lines = sheet.line_ids
            sheet.total_staff = len(lines)
            sheet.present_count = len(lines.filtered(lambda l: l.status == "present"))
            sheet.absent_count = len(lines.filtered(lambda l: l.status == "absent"))
            sheet.halfday_count = len(lines.filtered(lambda l: l.status == "halfday"))
            sheet.leave_count = len(lines.filtered(lambda l: l.status in ("leave", "halfday")))
            sheet.punched_in_count = len(lines.filtered(lambda l: l.punched_in))
            sheet.punched_out_count = len(lines.filtered(lambda l: l.punched_out))
            sheet.overtime_hours_total = sum(lines.mapped("overtime_hours"))
            sheet.fine_hours_total = sum(lines.mapped("fine_hours"))


    def action_open_sheet_lines(self):
        self.ensure_one()
        kpi = self.env.context.get("kpi")

        domain = [("sheet_id", "=", self.id)]
        title = _("Staff")

        if kpi == "total":
            title = _("Total Staff")
        elif kpi == "present":
            domain += [("status", "=", "present")]
            title = _("Present")
        elif kpi == "absent":
            domain += [("status", "=", "absent")]
            title = _("Absent")
        elif kpi == "halfday":
            domain += [("status", "=", "halfday")]
            title = _("Half Day")
        elif kpi == "leave":
            domain += [("status", "in", ("leave", "halfday"))]
            title = _("Leave")
        elif kpi == "punched_in":
            domain += [("check_in", "!=", False)]
            title = _("Punched In")
        elif kpi == "punched_out":
            domain += [("check_out", "!=", False)]
            title = _("Punched Out")
        elif kpi == "ot":
            domain += [("overtime_hours", ">", 0)]
            title = _("Overtime")
        elif kpi == "fine":
            domain += [("fine_hours", ">", 0)]
            title = _("Fine")

        list_view = self.env.ref(
            "bambus_hr_daily_ops.view_bambus_hr_attendance_sheet_line_list",
            raise_if_not_found=False
        )
        form_view = self.env.ref(
            "bambus_hr_daily_ops.view_bambus_hr_attendance_sheet_line_form",
            raise_if_not_found=False
        )

        views = []
        if list_view:
            views.append((list_view.id, "list"))
        if form_view:
            views.append((form_view.id, "form"))

        ctx = dict(self.env.context or {})
        ctx.update({"default_sheet_id": self.id})

        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": "bambus.hr.attendance.sheet.line",
            "view_mode": "list,form",          # ✅ Odoo 18
            "views": views or False,           # ✅ Force our views
            "domain": domain,
            "context": ctx,
            "target": "current",
    }

    @api.model
    def cron_create_today_sheet_if_missing(self):
        """Run at start of day: create today's sheet if not exists."""
        today = fields.Date.context_today(self)

        # If multi-company, create one per company
        companies = self.env.companies if "company_id" in self._fields else [False]

        for company in companies:
            domain = [("date", "=", today)]
            if company and "company_id" in self._fields:
                domain.append(("company_id", "=", company.id))

            if self.search_count(domain):
                continue

            vals = {"date": today}

            if company and "company_id" in self._fields:
                vals["company_id"] = company.id

            # Optional (only if your model has name and it’s required/used)
            if "name" in self._fields and not vals.get("name"):
                vals["name"] = f"Attendance Sheet - {today}"

            self.create(vals)


class BambusHrAttendanceSheetLine(models.Model):
    _name = "bambus.hr.attendance.sheet.line"
    _description = "Attendance Sheet Line"
    _order = "employee_id"

    sheet_id = fields.Many2one("bambus.hr.attendance.sheet", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="sheet_id.company_id", store=True, readonly=True)
    date = fields.Date(related="sheet_id.date", store=True, readonly=True)

    employee_id = fields.Many2one("hr.employee", required=True, index=True)
    department_id = fields.Many2one(related="employee_id.department_id", store=True, readonly=True)

    # Attendance snapshot
    attendance_id = fields.Many2one("hr.attendance", string="Attendance (First)", readonly=True)
    check_in = fields.Datetime(string="Punch In", readonly=True)
    check_out = fields.Datetime(string="Punch Out", readonly=True)
    worked_hours = fields.Float(string="Worked Hours", readonly=True)

    punched_in = fields.Boolean(compute="_compute_flags", store=False)
    punched_out = fields.Boolean(compute="_compute_flags", store=False)

    # Leave snapshot
    leave_id = fields.Many2one("hr.leave", string="Leave", readonly=True)
    leave_state = fields.Selection(related="leave_id.state", store=False, readonly=True)
    is_half_day_leave = fields.Boolean(string="Half Day Leave", readonly=True)

    status = fields.Selection(
        [("present", "Present"), ("absent", "Absent"), ("leave", "Leave"), ("halfday", "Half Day")],
        default="absent",
        required=True,
        index=True,
    )

    # OT / Fine editable values (and approvals)
    overtime_hours = fields.Float(string="OT Hours", digits=(16, 2))
    overtime_amount = fields.Monetary(string="OT Amount")
    overtime_state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft",
    )

    fine_hours = fields.Float(string="Fine Hours", digits=(16, 2))
    fine_amount = fields.Monetary(string="Fine Amount")
    fine_state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft",
    )

    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", store=False)

    # Contract / wage type (for Hourly/Monthly grouping)
    contract_id = fields.Many2one("hr.contract", string="Contract", readonly=True)
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


    def _bambus_check_line_locked(self, vals=None):
        for rec in self:
            if rec.sheet_id and rec.sheet_id.state == "approved":
                raise UserError(_("This sheet is approved; line cannot be edited."))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        # block adding new lines into approved sheet
        for r in recs:
            if r.sheet_id and r.sheet_id.state == "approved":
                raise UserError(_("Cannot add lines to an approved sheet."))
        return recs

    def write(self, vals):
        # allow compute refresh while not approved; block all edits after approved
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

    def _compute_day_data(self):
        """Refresh attendance/leave snapshot and status + OT/Fine snapshot."""
        Attendance = self.env["hr.attendance"].sudo()
        Leave = self.env["hr.leave"].sudo()

        # safety checks (module may not be installed in some DBs)
        has_fine_fields = ("bambus_fine_hours" in Attendance._fields and "bambus_fine_amount" in Attendance._fields)
        has_overtime_amount_field = ("bambus_overtime_amount" in Attendance._fields)

        for rec in self:
            rec.attendance_id = False
            rec.check_in = False
            rec.check_out = False
            rec.worked_hours = 0.0
            rec.leave_id = False
            rec.is_half_day_leave = False

            # NEW: reset OT/Fine snapshot
            rec.overtime_hours = 0.0
            rec.overtime_amount = 0.0
            rec.fine_hours = 0.0
            rec.fine_amount = 0.0

            if not rec.employee_id or not rec.date:
                continue

            start_dt, end_dt = rec._day_bounds_utc(rec.date)

            atts = Attendance.search([
                ("employee_id", "=", rec.employee_id.id),
                ("check_in", "<", fields.Datetime.to_string(end_dt)),
                "|",
                    ("check_out", "=", False),
                    ("check_out", ">", fields.Datetime.to_string(start_dt)),
            ], order="check_in asc")

            if atts:
                rec.attendance_id = atts[0]
                rec.check_in = atts[0].check_in

                total_hours = 0.0
                last_out = False

                # NEW: totals
                overtime_hours_total = 0.0
                overtime_amount_total = 0.0

                # pick LAST attendance of the day (where fine is stored)
                last_att = atts.sorted(key=lambda a: ((a.check_out or a.check_in), a.id))[-1]

                for a in atts:
                    total_hours += a.worked_hours or 0.0
                    if a.check_out:
                        last_out = a.check_out

                    # OT total (sum per punch OT allocation)
                    overtime_hours_total += (a.overtime_hours or 0.0)

                    # OT amount total (from attendance field)
                    if has_overtime_amount_field:
                        overtime_amount_total += (a.bambus_overtime_amount or 0.0)

                rec.check_out = last_out
                rec.worked_hours = total_hours

                # set OT totals
                rec.overtime_hours = overtime_hours_total
                rec.overtime_amount = overtime_amount_total

                # set Fine only from LAST attendance record
                if has_fine_fields and last_att:
                    rec.fine_hours = last_att.bambus_fine_hours or 0.0
                    rec.fine_amount = last_att.bambus_fine_amount or 0.0

            # Leave: find any leave covering this date
            leave = Leave.search([
                ("employee_id", "=", rec.employee_id.id),
                ("state", "!=", "refuse"),
                ("request_date_from", "<=", rec.date),
                ("request_date_to", ">=", rec.date),
            ], order="id desc", limit=1)

            if leave:
                rec.leave_id = leave
                if "request_unit_half" in leave._fields and leave.request_unit_half:
                    rec.is_half_day_leave = True

            # Decide status
            if rec.leave_id and rec.is_half_day_leave:
                rec.status = "halfday"
            elif rec.leave_id:
                rec.status = "leave"
            elif rec.attendance_id:
                rec.status = "present"
            else:
                rec.status = "absent"

            # Contract + Wage Type (Hourly/Monthly grouping)
            Contract = self.env["hr.contract"].sudo()
            contract = Contract.search([
                ("employee_id", "=", rec.employee_id.id),
                ("state", "in", ("draft", "open")),
                ("date_start", "<=", rec.date),
                "|", ("date_end", "=", False), ("date_end", ">=", rec.date),
            ], order="date_start desc", limit=1)

            rec.contract_id = contract
            rec.wage_type_display = _("No Contract")

            if contract:
                if "wage_type" in contract._fields:
                    val = contract.wage_type or ""
                    sel = contract._fields["wage_type"].selection
                    label = dict(sel).get(val) if isinstance(sel, (list, tuple)) else None
                    rec.wage_type_display = label or (val.replace("_", " ").title() if val else _("Wage Type"))
                elif "wage_type_id" in contract._fields and contract.wage_type_id:
                    rec.wage_type_display = contract.wage_type_id.display_name
                elif "schedule_pay" in contract._fields:
                    val = contract.schedule_pay or ""
                    sel = contract._fields["schedule_pay"].selection
                    label = dict(sel).get(val) if isinstance(sel, (list, tuple)) else None
                    rec.wage_type_display = label or (val.replace("_", " ").title() if val else _("Schedule"))
                else:
                    rec.wage_type_display = _("Contract")



    def action_refresh(self):
        self._compute_day_data()
        return True

    # --- Buttons (open popup wizards) ---
    def action_edit_attendance(self):
        self.ensure_one()
        if self.sheet_id.state == "approved":
            raise UserError(_("This sheet is approved. You cannot modify punches."))
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
        if self.sheet_id.state == "approved":
            raise UserError(_("This sheet is approved. You cannot modify punches."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Edit Overtime"),
            "res_model": "bambus.hr.overtime.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_line_id": self.id},
        }

    def action_edit_fine(self):
        self.ensure_one()
        if self.sheet_id.state == "approved":
            raise UserError(_("This sheet is approved. You cannot modify punches."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Fine"),
            "res_model": "bambus.hr.fine.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_line_id": self.id},
        }

    def action_mark_halfday_leave(self):
        self.ensure_one()
        if self.sheet_id.state == "approved":
            raise UserError(_("This sheet is approved. You cannot modify punches."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Mark Half Day Leave"),
            "res_model": "bambus.hr.leave.quick.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_line_id": self.id, "default_leave_unit": "half"},
        }

    def action_mark_full_leave(self):
        self.ensure_one()
        if self.sheet_id.state == "approved":
            raise UserError(_("This sheet is approved. You cannot modify punches."))
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
        if self.sheet_id.state == "approved":
            raise UserError(_("This sheet is approved. You cannot modify punches."))
        self.status = "absent"
        return True
