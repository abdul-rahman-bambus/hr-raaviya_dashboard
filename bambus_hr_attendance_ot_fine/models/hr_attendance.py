import pytz
from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

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

            d = fields.Date.to_date(att.check_in)
            contract = att._get_contract_on_date(att.employee_id, d)
            if not contract:
                continue

            wage_type = (getattr(contract, "wage_type", "") or "monthly").strip().lower()

            # Hourly flexible: no OT amount in this policy
            if wage_type == "hourly":
                continue

            if not getattr(contract, "is_overtime_allowed", False):
                continue

            rate = float(getattr(contract, "overtime_rate", 0.0) or 0.0)
            att.bambus_overtime_amount = max(att.overtime_hours or 0.0, 0.0) * rate


    # ---------- local day helper (same base as your grouping: context_timestamp) ----------
    def _bambus_local_day(self, check_in_dt):
        if not check_in_dt:
            return None
        return fields.Datetime.context_timestamp(self, check_in_dt).date()

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
