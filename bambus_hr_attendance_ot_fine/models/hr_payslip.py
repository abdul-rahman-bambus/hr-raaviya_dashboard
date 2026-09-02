# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta, time
import pytz
from collections import defaultdict
import logging


_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    days_excl_weekend_holidays = fields.Float("Regular Days", compute="_compute_all_stats", store=True)
    total_working_days = fields.Float("Regular Days", compute="_compute_all_stats", store=True)
    total_worked_hours_excl_ot = fields.Float("Regular Days", compute="_compute_all_stats", store=True)
    total_validated_overtime = fields.Float("Overtime", compute="_compute_all_stats", store=True)
    total_late_login_minutes = fields.Float("Late Hours", compute="_compute_all_stats", store=True)
    total_late_after_grace = fields.Float("Late after grace", compute="_compute_all_stats", store=True)

    weekend_days = fields.Float("Weekend", compute="_compute_all_stats", store=True)
    weekend_worked = fields.Float("Weekend", compute="_compute_all_stats", store=True)
    weekend_hours = fields.Float("Weekend", compute="_compute_all_stats", store=True)


    holiday_days = fields.Float("Public Holidays", compute="_compute_all_stats", store=True)
    holiday_worked = fields.Float("Public Holidays", compute="_compute_all_stats", store=True)
    holiday_hours = fields.Float("Public Holidays", compute="_compute_all_stats", store=True)

    total_overtime_amount = fields.Float(string="Overtime Amount", compute="_compute_all_stats", store=True)
    total_fine_hours = fields.Float(string="Fine Hours", compute="_compute_all_stats", store=True)
    total_fine_amount = fields.Float(string="Fine Amount", compute="_compute_all_stats", store=True)


    total_scheduled_hours = fields.Float(string="Scheduled Hours", compute="_compute_all_stats", store=True)
    total_shortfall_hours = fields.Float(string="Shortfall Hours", compute="_compute_all_stats", store=True)

    total_late_hours = fields.Float(string="Late Hours", compute="_compute_all_stats", store=True)
    total_early_leave_hours = fields.Float(string="Early Leave Hours", compute="_compute_all_stats", store=True)
    total_gap_hours = fields.Float(string="Gap Hours", compute="_compute_all_stats", store=True)
    total_fine_after_grace_hours = fields.Float(string="Fine After Grace", compute="_compute_all_stats", store=True)


    def get_weekend_days(self):
        Param = self.env['ir.config_parameter'].sudo()

        weekend_days = []

        if Param.get_param('hr_payroll.weekend_mon') == 'True': weekend_days.append(0)
        if Param.get_param('hr_payroll.weekend_tue') == 'True': weekend_days.append(1)
        if Param.get_param('hr_payroll.weekend_wed') == 'True': weekend_days.append(2)
        if Param.get_param('hr_payroll.weekend_thu') == 'True': weekend_days.append(3)
        if Param.get_param('hr_payroll.weekend_fri') == 'True': weekend_days.append(4)
        if Param.get_param('hr_payroll.weekend_sat') == 'True': weekend_days.append(5)
        if Param.get_param('hr_payroll.weekend_sun') == 'True': weekend_days.append(6)
        #if check_in_date.weekday() in weekend_days:
        return weekend_days


    # ---------------------------
    # Helpers
    # ---------------------------
    def _to_local(self, dt, tz):
        """Return tz-aware datetime in tz (tz is a pytz timezone)."""
        if not dt:
            return None
        if isinstance(dt, str):
            dt = fields.Datetime.from_string(dt)
        # assume stored in UTC if naive
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(tz)

    def _get_schedule_segments(self, calendar, day):
        """Return WORK segments only (exclude lunch/break if day_period exists)."""
        if not calendar:
            return []
        weekday = str(day.weekday())  # 0=Mon .. 6=Sun

        rules = calendar.attendance_ids.filtered(
            lambda r: r.dayofweek is not None and str(int(float(r.dayofweek))) == weekday
        )

        def _is_work(r):
            if "day_period" in r._fields:
                dp = (r.day_period or "").lower()
                if dp in ("lunch", "break"):
                    return False
                return (not dp) or (dp in ("morning", "afternoon"))
            return True

        rules = rules.filtered(_is_work).sorted(key=lambda r: r.hour_from or 0.0)

        segs = []
        for r in rules:
            try:
                hf = float(r.hour_from or 0.0)
                ht = float(r.hour_to or 0.0)
            except Exception:
                continue
            h1, m1 = int(hf), int(round((hf - int(hf)) * 60))
            h2, m2 = int(ht), int(round((ht - int(ht)) * 60))
            segs.append((time(h1, m1), time(h2, m2)))
        return segs



    # ---------------------------
    # Main compute
    # ---------------------------
    @api.depends(
        "date_from", "date_to", "employee_id", "contract_id",
        "employee_id.attendance_ids", "employee_id.attendance_ids.check_in", "employee_id.attendance_ids.check_out",
        "employee_id.attendance_ids.worked_hours", "employee_id.attendance_ids.overtime_hours", "employee_id.attendance_ids.bambus_scheduled_hours",
        "employee_id.attendance_ids.bambus_shortfall_hours",
    )
    def _compute_all_stats(self):
        Param = self.env["ir.config_parameter"].sudo()
        weekend_days = []
        if Param.get_param('hr_payroll.weekend_mon') == 'True': weekend_days.append(0)
        if Param.get_param('hr_payroll.weekend_tue') == 'True': weekend_days.append(1)
        if Param.get_param('hr_payroll.weekend_wed') == 'True': weekend_days.append(2)
        if Param.get_param('hr_payroll.weekend_thu') == 'True': weekend_days.append(3)
        if Param.get_param('hr_payroll.weekend_fri') == 'True': weekend_days.append(4)
        if Param.get_param('hr_payroll.weekend_sat') == 'True': weekend_days.append(5)
        if Param.get_param('hr_payroll.weekend_sun') == 'True': weekend_days.append(6)

        half_day_hrs = float(Param.get_param("hr_payroll.half_day_hours", 4) or 4)
        full_day_hrs = float(Param.get_param("hr_payroll.full_day_hours", 8) or 8)
        grace_minutes = int(Param.get_param("custom_hr_payroll.late_login_grace_minutes", 0) or 0)

        Attendance = self.env["hr.attendance"].sudo()
        CalendarLeave = self.env["resource.calendar.leaves"].sudo()

        for slip in self:
            # defaults
            slip.total_working_days = 0.0
            slip.total_worked_hours_excl_ot = 0.0
            slip.total_validated_overtime = 0.0
            slip.total_late_login_minutes = 0.0
            slip.total_late_after_grace = 0.0

            slip.weekend_days = 0.0
            slip.holiday_days = 0.0
            slip.days_excl_weekend_holidays = 0.0

            slip.weekend_worked = 0.0
            slip.weekend_hours = 0.0
            slip.holiday_worked = 0.0
            slip.holiday_hours = 0.0

            slip.total_overtime_amount = 0.0
            slip.total_fine_hours = 0.0
            slip.total_fine_amount = 0.0

            slip.total_scheduled_hours = 0.0
            slip.total_shortfall_hours = 0.0

            slip.total_late_hours = 0.0
            slip.total_early_leave_hours = 0.0
            slip.total_gap_hours = 0.0
            slip.total_fine_after_grace_hours = 0.0



            if not (slip.employee_id and slip.date_from and slip.date_to):
                continue

            emp = slip.employee_id
            contract = slip.contract_id

            # Worker hourly: simple totals from attendances (no OT/fine/late)
            if getattr(emp, "employee_type", False) == "worker" and contract and getattr(contract, "wage_type", "") == "hourly":
                # Billable hours are capped per LOCAL day at the contract's
                # hourly_wage_hour_limit ("cannot be billed beyond this time").
                # Raw attendance worked_hours are left authentic.
                slip.total_scheduled_hours = 0.0
                slip.total_shortfall_hours = 0.0
                continue

            tzname = (contract.resource_calendar_id.tz if contract and contract.resource_calendar_id and contract.resource_calendar_id.tz else (self.env.user.tz or "UTC"))

            # public holidays for this employee calendar (resource_id=False only)
            public_holidays = set()
            if contract and contract.resource_calendar_id:
                leaves = CalendarLeave.search([
                    ("calendar_id", "=", contract.resource_calendar_id.id),
                    ("resource_id", "=", False),
                    ("date_from", "<=", fields.Datetime.to_string(datetime.combine(slip.date_to, time.max))),
                    ("date_to", ">=", fields.Datetime.to_string(datetime.combine(slip.date_from, time.min))),
                ])
                for lv in leaves:
                    if not (lv.date_from and lv.date_to):
                        continue
                    s_local = fields.Datetime.context_timestamp(self.with_context(tz=tzname), lv.date_from).date()
                    e_local = fields.Datetime.context_timestamp(self.with_context(tz=tzname), lv.date_to).date()
                    cur = s_local
                    while cur <= e_local:
                        if slip.date_from <= cur <= slip.date_to:
                            public_holidays.add(cur)
                        cur += timedelta(days=1)

            # fetch attendances in range
            start_dt = datetime.combine(slip.date_from, time.min)
            end_dt = datetime.combine(slip.date_to, time.max)
            atts = Attendance.search([
                ("employee_id", "=", emp.id),
                ("check_in", "<=", fields.Datetime.to_string(end_dt)),
                "|",
                    ("check_out", "=", False),
                    ("check_out", ">=", fields.Datetime.to_string(start_dt)),
            ], order="check_in asc")

            # group by local date (check_in local)
            by_day = defaultdict(lambda: Attendance.browse())
            for a in atts:
                if not a.check_in:
                    continue
                d = fields.Datetime.context_timestamp(self.with_context(tz=tzname), a.check_in).date()
                if slip.date_from <= d <= slip.date_to:
                    by_day[d] |= a

            has_ot_amount = ("bambus_overtime_amount" in Attendance._fields)
            has_fine = ("bambus_fine_hours" in Attendance._fields and "bambus_fine_amount" in Attendance._fields)
            has_late = ("bambus_late_minutes" in Attendance._fields)
            has_sched = ("bambus_scheduled_hours" in Attendance._fields)
            has_short = ("bambus_shortfall_hours" in Attendance._fields)
            has_early = ("bambus_early_leave_minutes" in Attendance._fields)
            has_gap = ("bambus_gap_minutes" in Attendance._fields)



            total_days = (slip.date_to - slip.date_from).days + 1
            slip.weekend_days = float(sum(1 for i in range(total_days)
                                         if (slip.date_from + timedelta(days=i)).weekday() in weekend_days))
            slip.holiday_days = float(len([d for d in public_holidays if slip.date_from <= d <= slip.date_to]))
            slip.days_excl_weekend_holidays = float(sum(1 for i in range(total_days)
                                                      if (slip.date_from + timedelta(days=i)).weekday() not in weekend_days
                                                      and (slip.date_from + timedelta(days=i)) not in public_holidays))

            late_by_month = defaultdict(int)

            for i in range(total_days):
                d = slip.date_from + timedelta(days=i)
                day_att = by_day.get(d, Attendance.browse())

                worked = sum(day_att.mapped("worked_hours")) if day_att else 0.0

                ot = 0.0
                ot_amount = 0.0
                if emp.employee_type != "worker" and day_att:
                    ot = sum(max(0.0, (a.overtime_hours or 0.0)) for a in day_att)
                    if has_ot_amount:
                        ot_amount = sum((a.bambus_overtime_amount or 0.0) for a in day_att)

                # last-attendance values (stored values only)
                scheduled_today = 0.0
                if day_att:
                    last = day_att.sorted(key=lambda a: ((a.check_out or a.check_in), a.id))[-1]
                    if has_sched:
                        scheduled_today = float(last.bambus_scheduled_hours or 0.0)

                # fallback schedule if not stored
                if scheduled_today <= 0:
                    scheduled_today = float(full_day_hrs)

                # ✅ for DAY COUNT: use effective worked capped by schedule (OT should not reduce day count)
                effective_worked_for_daycount = min(float(worked or 0.0), float(scheduled_today or 0.0))

                if effective_worked_for_daycount >= float(full_day_hrs):
                    day_fraction = 1.0
                elif effective_worked_for_daycount >= float(half_day_hrs):
                    day_fraction = 0.5
                else:
                    day_fraction = 0.0

                # ✅ for HOURS BUCKETS: keep regular base hours excluding OT (as you already do)
                base_hours = max(0.0, float(worked or 0.0) - float(ot or 0.0))


                is_weekend = d.weekday() in weekend_days
                is_holiday = d in public_holidays

                # late/fine from LAST attendance of the day only (stored values)
                late_mins = 0
                early_mins = 0
                gap_mins = 0
                fine_h = 0.0
                fine_amt = 0.0
                sched_h = 0.0
                short_h = 0.0
                if day_att:
                    last = day_att.sorted(key=lambda a: ((a.check_out or a.check_in), a.id))[-1]

                    if has_late:
                        late_mins = int(last.bambus_late_minutes or 0)

                    if has_early:
                        early_mins = int(last.bambus_early_leave_minutes or 0)

                    if has_gap:
                        gap_mins = int(last.bambus_gap_minutes or 0)

                    if has_fine:
                        fine_h = float(last.bambus_fine_hours or 0.0)
                        fine_amt = float(last.bambus_fine_amount or 0.0)

                    # NEW: scheduled + shortfall from last punch (stored on attendance)
                    if has_sched:
                        sched_h = float(last.bambus_scheduled_hours or 0.0)
                    if has_short:
                        short_h = float(last.bambus_shortfall_hours or 0.0)


                late_by_month[(d.year, d.month)] += late_mins

                if is_weekend:
                    slip.weekend_worked += day_fraction
                    slip.weekend_hours += base_hours + ot
                elif is_holiday:
                    slip.holiday_worked += day_fraction
                    slip.holiday_hours += base_hours + ot
                else:
                    slip.total_working_days += day_fraction
                    slip.total_worked_hours_excl_ot += base_hours

                slip.total_validated_overtime += ot
                slip.total_overtime_amount += ot_amount
                slip.total_late_hours += late_mins / 60.0
                slip.total_early_leave_hours += early_mins / 60.0
                slip.total_gap_hours += gap_mins / 60.0
                slip.total_fine_hours += fine_h
                slip.total_fine_amount += fine_amt
                slip.total_scheduled_hours += sched_h
                slip.total_shortfall_hours += short_h

            total_late_raw = sum(late_by_month.values())

            total_late_after = sum(max(0, m - grace_minutes) for m in late_by_month.values())

            slip.total_late_login_minutes = total_late_raw / 60.0
            slip.total_late_after_grace = total_late_after / 60.0
            slip.total_fine_after_grace_hours = slip.total_late_after_grace


    def get_worked_day_lines(self, contracts, date_from, date_to):
        """
        If contract has no special working flags -> fallback to default (Cybrosys)
        Otherwise -> custom logic.
        """
        default_res = super(HrPayslip, self).get_worked_day_lines(contracts, date_from, date_to)
        # for each slip
        for slip in self:
            contract = slip.contract_id

            # Case A: no weekend working + no public holiday working
            # OR wage type = hourly
            if (not contract.weekend_special_working and not contract.public_holidays_working) \
                or contract.wage_type == 'hourly':

                return default_res   # <-- RETURN ORIGINAL ODOO OUTPUT

            # Case B: special config enabled → custom output
            res = []

            # Normal days
            res.append({
                'name': 'Normal Working Days',
                'sequence': 1,
                'code': 'DAYSWORKED',
                'number_of_days': slip.total_working_days,
                'number_of_hours': slip.total_worked_hours_excl_ot,
                'contract_id': contract.id,
            })

            # WEEKEND worked ONLY IF enabled
            if slip.weekend_worked > 0 and contract.weekend_special_working:
                res.append({
                    'name': 'Weekend Working Days',
                    'sequence': 5,
                    'code': 'WEEKEND',
                    'number_of_days': slip.weekend_worked,
                    'number_of_hours': slip.weekend_hours,
                    'contract_id': contract.id,
                })

            # PUBLIC HOLIDAYS worked ONLY IF enabled
            if slip.holiday_worked > 0 and contract.public_holidays_working:
                res.append({
                    'name': 'Public Holidays',
                    'sequence': 10,
                    'code': 'HOLIDAYS',
                    'number_of_days': slip.holiday_worked,
                    'number_of_hours': slip.holiday_hours,
                    'contract_id': contract.id,
                })

            return res
