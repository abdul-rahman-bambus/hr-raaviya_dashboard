# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta, time
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT

from collections import defaultdict
import pytz

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


    total_worker_hours = fields.Float("Total Worked Hours (Worker)", compute="_compute_worker_hours", store=True)
    total_worker_days = fields.Float("Total Worked Days (Worker)", compute="_compute_worker_hours", store=True)
    
    employee_type = fields.Selection(related='employee_id.employee_type')


    def _bambus_hourly_billable_hours(self, employee, contract, date_from, date_to):
        """
        Billable worked hours for an hourly-wage employee over [date_from, date_to],
        where EACH LOCAL DAY is capped at contract.hourly_wage_hour_limit.

        This is the single place the "Hourly Wage Hour Limit" is enforced:
        the field means "the employee cannot be billed beyond this time" *per day*.
        Raw hr.attendance.worked_hours are left completely authentic - only the
        billable total returned here is capped. A limit of 0 means "no cap"
        (all 24h/day billable), matching the field's help text.

        Returns (billable_hours, num_attendance_days).
        """
        if not employee or not contract or not date_from or not date_to:
            return 0.0, 0

        # FIX 1: Protect against strings passed during Compute Sheet / onchange re-evaluations
        if isinstance(date_from, str):
            date_from = fields.Date.from_string(date_from)
        if isinstance(date_to, str):
            date_to = fields.Date.from_string(date_to)

        limit = float(getattr(contract, "hourly_wage_hour_limit", 0.0) or 0.0)

        tzname = (contract.resource_calendar_id.tz
                  if contract.resource_calendar_id and contract.resource_calendar_id.tz
                  else (self.env.user.tz or "UTC"))
        local_tz = pytz.timezone(tzname)

        # 1. Create local datetime boundaries (Midnight to 23:59:59 in local TZ)
        local_dfrom = local_tz.localize(datetime.combine(date_from, time.min))
        local_dto = local_tz.localize(datetime.combine(date_to, time.max))

        # 2. Convert to naive UTC 
        utc_dfrom = local_dfrom.astimezone(pytz.utc).replace(tzinfo=None)
        utc_dto = local_dto.astimezone(pytz.utc).replace(tzinfo=None)

        # FIX 2: Force standard string format so the ORM never drops the query during recompute
        utc_dfrom_str = utc_dfrom.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        utc_dto_str = utc_dto.strftime(DEFAULT_SERVER_DATETIME_FORMAT)

        # 3. Query using the properly formatted UTC boundaries
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', utc_dfrom_str),
            ('check_in', '<=', utc_dto_str),
        ])

        # sum authentic worked hours per LOCAL day, then cap each day
        per_day = defaultdict(float)
        for att in attendances:
            if not att.check_in:
                continue
            d = fields.Datetime.context_timestamp(self.with_context(tz=tzname), att.check_in).date()
            per_day[d] += (att.worked_hours or 0.0)

        if limit > 0:
            billable = sum(min(hrs, limit) for hrs in per_day.values())
        else:
            billable = sum(per_day.values())

        return billable, len(per_day)

    def _get_worker_total_hours(self, slip):
        """Billable (per-day capped) worked hours + attendance days for hourly employees."""
        employee = slip.employee_id
        contract = slip.contract_id

        if not employee or not contract or contract.wage_type != 'hourly':
            return 0.0, 0

        return self._bambus_hourly_billable_hours(
            employee, contract, slip.date_from, slip.date_to
        )

    @api.depends("employee_id", "contract_id", "date_from", "date_to")
    def _compute_worker_hours(self):
        for slip in self:
            slip.total_worker_hours = 0.0
            slip.total_worker_days = 0.0
            if (not slip.employee_id or 
                not slip.contract_id or 
                slip.contract_id.wage_type != 'hourly' or 
                not slip.date_from):
                continue
            slip.total_worker_hours, slip.total_worker_days = self._get_worker_total_hours(slip)


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
        """
        Return list of (time_start, time_end) tuples for the weekday of `day`.
        E.g. [(time(9,45), time(14,0)), (time(14,45), time(18,45))]
        """
        if not calendar:
            return []
        Att = self.env["resource.calendar.attendance"]
        weekday = str(day.weekday())  # 0=Mon .. 6=Sun
        rules = Att.search([("calendar_id", "=", calendar.id), ("dayofweek", "=", weekday)], order="hour_from asc")
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
    @api.depends("date_from", "date_to", "employee_id", "contract_id", "employee_id.attendance_ids")
    def _compute_all_stats(self):
        for slip in self:
            # initialize
            slip.days_excl_weekend_holidays = 0.0
            slip.total_working_days = 0.0
            slip.total_worked_hours_excl_ot = 0.0
            slip.total_validated_overtime = 0.0
            slip.total_late_login_minutes = 0.0
            slip.total_late_after_grace = 0.0
            slip.weekend_days = 0.0
            slip.weekend_worked = 0.0
            slip.weekend_hours = 0.0
            slip.holiday_days = 0
            slip.holiday_worked = 0.0
            slip.holiday_hours = 0.0

            # guards
            if not (slip.date_from and slip.date_to and slip.employee_id and slip.contract_id and slip.contract_id.resource_calendar_id):
                continue

            start = fields.Date.from_string(slip.date_from)
            end = fields.Date.from_string(slip.date_to)
            employee = slip.employee_id
            calendar = slip.contract_id.resource_calendar_id

            tz_str = self.env.user.tz or self.env.context.get("tz") or "UTC"
            tz = pytz.timezone(tz_str)

            # --- Sundays in the month (calendar count) ---
            all_dates = []
            cur = start
            while cur <= end:
                all_dates.append(cur)
                cur = cur + timedelta(days=1)
            
            weekend_days = self.get_weekend_days()
            weekend_dates_in_period = [d for d in all_dates if d.weekday() in weekend_days]

            slip.weekend_days = float(len(weekend_dates_in_period))
            
            half_day_hrs = float(self.env['ir.config_parameter'].sudo().get_param('hr_payroll.half_day_hours', 4))
            full_day_hrs = float(self.env['ir.config_parameter'].sudo().get_param('hr_payroll.full_day_hours', 8))

            # --- Public holidays from resource.calendar.leaves (global leaves: resource_id = False) ---
            CalendarLeave = self.env["resource.calendar.leaves"]
            ph_leaves = CalendarLeave.search([
                ("calendar_id", "=", calendar.id),
                ("resource_id", "=", False),
                ("date_from", "<=", fields.Datetime.to_string(datetime.combine(end, time.max))),
                ("date_to", ">=", fields.Datetime.to_string(datetime.combine(start, time.min))),
            ])
            public_holiday_dates = set()
            for lv in ph_leaves:
                s_local = self._to_local(lv.date_from, tz).date()
                e_local = self._to_local(lv.date_to, tz).date()
                d = s_local
                while d <= e_local:
                    if start <= d <= end:
                        public_holiday_dates.add(d)
                    d += timedelta(days=1)
            slip.holiday_days = len(public_holiday_dates)

            # Generate all days between start and end
            total_days_list = [
            start + timedelta(days=i)
            for i in range((end - start).days + 1)]
            total_month_days = len(total_days_list) 
            slip.days_excl_weekend_holidays = (total_month_days - (slip.holiday_days + slip.weekend_days))
            # --- fetch attendance rows intersecting the payslip period ---
            Attendance = self.env["hr.attendance"]
            attends = Attendance.search([
                ("employee_id", "=", employee.id),
                ("check_in", "<=", fields.Datetime.to_string(datetime.combine(end, time.max))),
                ("check_out", ">=", fields.Datetime.to_string(datetime.combine(start, time.min))),
            ], order="check_in asc")

            grace_minutes = int(self.env['ir.config_parameter'].sudo().get_param(
            'custom_hr_payroll.late_login_grace_minutes', 0) or 0)
            grace_hours = grace_minutes / 60.0
            # group attendances by local date (no overnight splitting)
            daily = {}
            period_start_dt = tz.localize(datetime.combine(start, time.min))
            period_end_dt = tz.localize(datetime.combine(end, time.max))
            for a in attends:
                if not a.check_in or not a.check_out:
                    continue
                ci = self._to_local(a.check_in, tz)
                co = self._to_local(a.check_out, tz)
                # discard if outside payslip period
                if co <= period_start_dt or ci >= period_end_dt:
                    continue
                # clip to period
                if ci < period_start_dt:
                    ci = period_start_dt
                if co > period_end_dt:
                    co = period_end_dt
                day = ci.date()
                daily.setdefault(day, []).append((ci, co))

            # totals
            total_days = 0.0
            total_normal_hours = 0.0
            total_ot_hours = 0.0
            total_late_minutes = 0.0
            weekend_worked_days = 0.0
            weekend_total_hours = 0.0
            holiday_worked_days = 0.0
            holiday_total_hours = 0.0
            normal_ot_hours = 0.0
            weekend_ot_hours = 0.0
            holiday_ot_hours = 0.0

            # iterate per-day
            for day_date, segs in sorted(daily.items()):
                # schedule segments for that date
                sched_time_segs = self._get_schedule_segments(calendar, day_date)
                if not sched_time_segs:
                    continue
                # convert schedule to tz-aware datetimes
                schedule_dt = [(tz.localize(datetime.combine(day_date, s)), tz.localize(datetime.combine(day_date, e))) for s, e in sched_time_segs]
                last_sched_end = schedule_dt[-1][1]

                # determine special day
                #is_sunday = (day_date.weekday() == 6)
                is_weekend = (day_date.weekday() in weekend_days)
                is_holiday = (day_date in public_holiday_dates)
                #is_special = is_sunday or is_holiday

                # --- LATE (per segment, full minutes only) ---
                check_ins = sorted(ci for ci, co in segs)
                day_late_minutes = 0

                for seg_start, seg_end in schedule_dt:

                    # segment duration
                    duration_sec = (seg_end - seg_start).total_seconds()

                    # skip lunch / break segments
                    if duration_sec < 3600:
                        continue

                    eligible = [ci for ci in check_ins if seg_start < ci <= seg_end]
                    if not eligible:
                        continue

                    matched_ci = min(eligible)

                    if matched_ci > seg_start:
                        diff_seconds = (matched_ci - seg_start).total_seconds()
                        late_full_minutes = int(diff_seconds // 60)
                        day_late_minutes += late_full_minutes

                    check_ins.remove(matched_ci)

                # --- normal hours (attendance ∩ schedule) and OT (after last scheduled end) ---
                normal_seconds = 0
                ot_seconds = 0
                for ci, co in segs:
                    for seg_start, seg_end in schedule_dt:
                        ov_start = max(ci, seg_start)
                        ov_end = min(co, seg_end)
                        if ov_end > ov_start:
                            normal_seconds += int((ov_end - ov_start).total_seconds())
                    # OT portion
                    if co > last_sched_end:
                        ot_start = max(ci, last_sched_end)
                        if co > ot_start:
                            ot_seconds += int((co - ot_start).total_seconds())

                day_normal_hours = normal_seconds / 3600.0
                day_ot_hours = ot_seconds / 3600.0

                raw_normal = day_normal_hours
                raw_ot = day_ot_hours

                # normalize normal hours
                if raw_normal >= full_day_hrs:
                    day_fraction = 1.0
                    day_normal_hours = full_day_hrs

                elif raw_normal >= half_day_hrs:
                    day_fraction = 0.5
                    day_normal_hours = raw_normal

                else:
                    day_fraction = 0.0
                    day_normal_hours = 0.0

                # accumulate                
                if is_holiday:
                    holiday_worked_days += day_fraction
                    holiday_total_hours += (day_normal_hours + raw_ot)
                    
                elif is_weekend:
                    weekend_worked_days += day_fraction
                    weekend_total_hours += (day_normal_hours + raw_ot)

                else:
                    total_days += day_fraction
                    total_normal_hours += day_normal_hours
                    total_ot_hours += raw_ot

                # ALWAYS accumulate OT and late time
                #total_ot_hours += raw_ot              # OT always in hours
                total_late_minutes += day_late_minutes  # late in *minutes*

            # convert total late minutes to hours for storage/display
            total_late_hours = total_late_minutes / 60.0
            late_after_grace_hours = max(0.0, total_late_hours - (grace_minutes / 60.0))
            slip.total_late_login_minutes = float(total_late_hours)
            slip.total_late_after_grace = float(late_after_grace_hours)
            slip.total_working_days = float(total_days)
            slip.total_worked_hours_excl_ot = float(total_normal_hours)
            slip.total_validated_overtime = float(total_ot_hours)
            slip.weekend_worked = float(weekend_worked_days)
            slip.weekend_hours = float(weekend_total_hours)
            slip.holiday_worked = float(holiday_worked_days)
            slip.holiday_hours = float(holiday_total_hours)


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
