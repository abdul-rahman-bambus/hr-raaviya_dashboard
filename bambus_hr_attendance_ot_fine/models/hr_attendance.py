import pytz
from odoo import api, fields, models
from odoo.tools import create_index


_SCOPED_OVERTIME = object()


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    def init(self):
        super().init()
        create_index(self.env.cr, "bambus_hr_attendance_check_in_employee_idx",
                     self._table, ["check_in", "employee_id"])

    def _recompute_bambus_overtime_hours(self):
        attendances = self.with_context(bambus_scoped_overtime=_SCOPED_OVERTIME)
        self.env.add_to_compute(self._fields["overtime_hours"], attendances)
        attendances._recompute_recordset(["overtime_hours"])
        attendances.modified(["overtime_hours"])

    @api.depends("worked_hours")
    def _compute_overtime_hours(self):
        if self.env.context.get("bambus_scoped_overtime") is not _SCOPED_OVERTIME:
            return super()._compute_overtime_hours()

        timezone_by_name = {
            name: pytz.timezone(name)
            for name in self.employee_id.resource_calendar_id.mapped("tz") if name
        }
        requested_days = {}
        for attendance in self:
            employee = attendance.employee_id
            timezone = timezone_by_name.get(employee.resource_calendar_id.tz)
            if timezone and attendance.check_in and attendance.worked_hours:
                day = pytz.utc.localize(attendance.check_in).astimezone(timezone).date()
                requested_days[employee.id, day] = timezone
        if not requested_days:
            self.overtime_hours = 0.0
            return

        self.flush_model(["worked_hours", "employee_id", "check_in"])
        self.env["hr.attendance.overtime"].flush_model(["employee_id", "date", "duration", "adjustment"])
        employee_ids, dates = zip(*requested_days)
        # Odoo allocates overtime across all punches on the same employee
        # calendar date. Keep those punches even if only one is being updated.
        # The UTC bounds use the index. The local-date check handles DST and
        # uses the same timezone aliases as the attendance policy.
        self.env.cr.execute("""
            WITH requested_days AS (
                SELECT employee_id, day
                  FROM unnest(%s::integer[], %s::date[]) AS dates(employee_id, day)
            )
            SELECT punch.id, punch.check_in, punch.worked_hours, overtime.id,
                   overtime.duration, requested_days.employee_id, requested_days.day
              FROM requested_days
              JOIN hr_attendance_overtime overtime
                ON overtime.employee_id = requested_days.employee_id
               AND overtime.date = requested_days.day
               AND overtime.adjustment IS FALSE
              JOIN hr_attendance punch
                ON punch.employee_id = requested_days.employee_id
               AND punch.check_in >= requested_days.day::timestamp - INTERVAL '1 day'
               AND punch.check_in < requested_days.day::timestamp + INTERVAL '2 days'
             WHERE punch.worked_hours <> 0
             ORDER BY punch.check_in DESC
        """, [list(employee_ids), list(dates)])

        remaining_by_day = {}
        hours_by_punch = {}
        for punch_id, check_in, worked, overtime_id, duration, employee_id, day in self.env.cr.fetchall():
            timezone = requested_days[employee_id, day]
            if pytz.utc.localize(check_in).astimezone(timezone).date() != day:
                continue
            remaining = remaining_by_day.setdefault(overtime_id, duration)
            if remaining < 0:
                hours_by_punch[punch_id] = remaining
                remaining_by_day[overtime_id] = 0
            elif remaining > 0:
                if remaining > worked:
                    hours_by_punch[punch_id] = worked
                    remaining_by_day[overtime_id] = remaining - worked
                else:
                    # Keep Odoo's percentage arithmetic for split punches.
                    regular_percentage = ((worked - remaining) / worked) * 100
                    hours_by_punch[punch_id] = worked * ((100 - regular_percentage) / 100)
                    remaining_by_day[overtime_id] = 0

        for attendance in self:
            attendance.overtime_hours = hours_by_punch.get(attendance.id, 0.0)

    # Amount based on Odoo overtime_hours (can be negative)
    bambus_overtime_amount = fields.Monetary(
        string="Overtime Amount",
        currency_field="currency_id",
        compute="_compute_bambus_overtime_amount",
        store=False,   # keep simple + always fresh
    )

    # Stored only on LAST attendance of the day
    bambus_fine_hours = fields.Float(string="Fine Hours")
    bambus_fine_amount = fields.Monetary(string="Fine Amount", currency_field="currency_id")
    bambus_late_minutes = fields.Integer(string="Late Minutes")
    bambus_scheduled_hours = fields.Float(string="Scheduled Hours", default=0.0)
    bambus_shortfall_hours = fields.Float(string="Shortfall Hours", default=0.0)
    bambus_late_hhmm = fields.Char(string="Late (HH:MM)", compute="_compute_bambus_late_display", store=False)
    bambus_late_hours = fields.Float(string="Late (Hours)", compute="_compute_bambus_late_display", store=False)
    bambus_early_leave_minutes = fields.Integer(string="Early Leave Minutes")
    bambus_gap_minutes = fields.Integer(string="Gap Minutes")  # shortfall not explained by late or early-leave
    bambus_early_leave_hhmm = fields.Char(string="Early Leave (HH:MM)", compute="_compute_bambus_breakdown_display", store=False)
    bambus_gap_hhmm = fields.Char(string="Gap (HH:MM)", compute="_compute_bambus_breakdown_display", store=False)

    @api.depends("bambus_early_leave_minutes", "bambus_gap_minutes")
    def _compute_bambus_breakdown_display(self):
        for rec in self:
            def fmt(mins):
                mins = int(mins or 0)
                return f"{mins//60:02d}:{mins%60:02d}"
            rec.bambus_early_leave_hhmm = fmt(rec.bambus_early_leave_minutes)
            rec.bambus_gap_hhmm = fmt(rec.bambus_gap_minutes)




    currency_id = fields.Many2one(related="employee_id.company_id.currency_id", store=True, readonly=True)

    @api.depends("bambus_late_minutes")
    def _compute_bambus_late_display(self):
        for rec in self:
            mins = int(rec.bambus_late_minutes or 0)
            hh = mins // 60
            mm = mins % 60
            rec.bambus_late_hhmm = f"{hh:02d}:{mm:02d}"
            rec.bambus_late_hours = mins / 60.0

    # ---------- contract on date ----------
    def _get_contract_on_date(self, employee, d):
        Contract = self.env["hr.contract"].sudo()
        return Contract.search([
            ("employee_id", "=", employee.id),
            ("state", "!=", "cancel"),
            "|", ("date_start", "=", False), ("date_start", "<=", d),
            "|", ("date_end", "=", False), ("date_end", ">=", d),
        ], order="date_start desc, id desc", limit=1)

    @api.depends("overtime_hours", "employee_id", "check_in")
    def _compute_bambus_overtime_amount(self):
        for att in self:
            att.bambus_overtime_amount = 0.0
            if not att.employee_id or not att.check_in:
                continue

            d = att._bambus_local_day(att.check_in)
            contract = att._get_contract_on_date(att.employee_id, d)
            if not contract:
                continue

            wage_type = (getattr(contract, "wage_type", "") or "monthly").strip().lower()

            # Hourly flexible: no OT amount in this policy
            if wage_type == "hourly":
                continue

            template = att.employee_id._get_attendance_automation_template(d)
            if not template or not template.overtime_enabled:
                continue

            rate = template.resolve_overtime_rate(contract)[0]
            att.bambus_overtime_amount = max(att.overtime_hours or 0.0, 0.0) * rate


    # ---------- local day helper (same base as your grouping: context_timestamp) ----------
    def _bambus_local_day(self, check_in_dt):
        if not check_in_dt:
            return None
        self.ensure_one()
        employee = self.employee_id
        tzname = employee.resource_calendar_id.tz or self.env.user.tz or "UTC"
        day = fields.Datetime.context_timestamp(self.with_context(tz=tzname), check_in_dt).date()
        contract = self._get_contract_on_date(employee, day)
        if contract.resource_calendar_id.tz:
            tzname = contract.resource_calendar_id.tz
        return fields.Datetime.context_timestamp(self.with_context(tz=tzname), check_in_dt).date()

    # ---------- recompute only impacted employee+day ----------
    def _bambus_recompute_impacted(self, impacted):
        """
        impacted = set of tuples: (employee_id, day_date)
        """
        if not impacted:
            return
        # Ensure worked_hours is written before recompute reads it
        self.env["hr.attendance"].flush_model(["worked_hours", "check_in", "check_out", "employee_id"])

        ot = self.env["hr.attendance.overtime"].sudo()
        # run per employee/day (fast)
        for emp_id, day in impacted:
            ot.bambus_recompute_range([emp_id], day, day)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)

        # avoid recursion / internal writes
        if self.env.context.get("bambus_skip_recompute"):
            return recs

        impacted = set()
        for r in recs:
            if r.employee_id and r.check_in:
                impacted.add((r.employee_id.id, r._bambus_local_day(r.check_in)))
            # safety: if checkout exists and crosses date boundaries, include that day too
            if r.employee_id and r.check_out:
                impacted.add((r.employee_id.id, r._bambus_local_day(r.check_out)))

        # ensure stored worked_hours is available
        self.env["hr.attendance"].flush_model(["worked_hours", "check_in", "check_out", "employee_id"])

        self._bambus_recompute_impacted(impacted)
        return recs

    def unlink(self):
        if self.env.context.get("bambus_skip_recompute"):
            return super().unlink()

        impacted = set()
        for r in self:
            if r.employee_id and r.check_in:
                impacted.add((r.employee_id.id, r._bambus_local_day(r.check_in)))
            if r.employee_id and r.check_out:
                impacted.add((r.employee_id.id, r._bambus_local_day(r.check_out)))

        res = super().unlink()

        # recompute after deletion too
        self.env["hr.attendance"]._bambus_recompute_impacted(impacted)
        return res

    def write(self, vals):
        # avoid recursion when recompute itself writes fine fields
        if self.env.context.get("bambus_skip_recompute"):
            return super().write(vals)

        trigger_fields = {"check_in", "check_out", "employee_id"}
        need = bool(trigger_fields.intersection(vals.keys()))
        if not need:
            return super().write(vals)

        before = [(r.employee_id.id, r._bambus_local_day(r.check_in)) for r in self]

        res = super().write(vals)

        after = [(r.employee_id.id, r._bambus_local_day(r.check_in)) for r in self]

        impacted = set()
        for emp_id, day in before + after:
            if emp_id and day:
                impacted.add((emp_id, day))

        self._bambus_recompute_impacted(impacted)
        return res
