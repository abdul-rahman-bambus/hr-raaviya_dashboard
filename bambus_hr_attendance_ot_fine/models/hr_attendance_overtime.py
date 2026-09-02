import pytz
from datetime import datetime, timedelta, date
from collections import defaultdict

from odoo import api, fields, models


class HrAttendanceOvertime(models.Model):
    _inherit = "hr.attendance.overtime"

    # ---------- helpers ----------
    def _date_list(self, start_date, end_date):
        s = fields.Date.to_date(start_date)
        e = fields.Date.to_date(end_date)
        out = []
        cur = s
        while cur <= e:
            out.append(cur)
            cur += timedelta(days=1)
        return out

    def _get_contract_on_date(self, employee, d):
        Contract = self.env["hr.contract"].sudo()
        return Contract.search([
            ("employee_id", "=", employee.id),
            ("state", "!=", "cancel"),
            "|", ("date_start", "=", False), ("date_start", "<=", d),
            "|", ("date_end", "=", False), ("date_end", ">=", d),
        ], order="date_start desc, id desc", limit=1)

    def _get_calendar_tz(self, employee, contract):
        cal = (contract.resource_calendar_id if contract and contract.resource_calendar_id else False) or employee.resource_calendar_id
        return (cal.tz if cal and cal.tz else False) or (self.env.user.tz or "UTC")

    def _get_shift_rules_for_employee_on_date(self, employee, dt_date):
        """
        Return working periods.
        Include day_period morning/afternoon AND also lines with no day_period (common calendars).
        Exclude lunch/break if it exists.
        """
        contract = employee.contract_id or (employee.contract_ids[:1] if employee.contract_ids else False)
        if not contract or not contract.resource_calendar_id:
            return []
        cal = contract.resource_calendar_id

        dow = dt_date.weekday()
        def _is_work(r):
            dp = (r.day_period or "").lower()
            if dp in ("lunch", "break"):
                return False
            # include morning/afternoon OR empty
            return (not dp) or (dp in ("morning", "afternoon"))

        rules = cal.attendance_ids.filtered(
            lambda r:
                r.dayofweek is not None
                and str(int(float(r.dayofweek))) == str(dow)
                and _is_work(r)
        )

        shifts = [(float(r.hour_from or 0.0), float(r.hour_to or 0.0)) for r in rules]
        return sorted(shifts, key=lambda x: x[0])

    def _shift_bounds_local(self, tz, d, shifts):
        bounds = []
        for hf, ht in shifts:
            sh = int(hf); sm = int(round((hf - sh) * 60))
            eh = int(ht); em = int(round((ht - eh) * 60))
            start = tz.localize(datetime(d.year, d.month, d.day, sh, sm, 0))
            end = tz.localize(datetime(d.year, d.month, d.day, eh, em, 0))
            if end <= start:
                end = end + timedelta(days=1)
            bounds.append((start, end))
        return bounds

    def _ctx_ts(self, tzname, dt_utc):
        return fields.Datetime.context_timestamp(self.with_context(tz=tzname), dt_utc)

    def _monthly_scheduled_hours(self, employee, year, month):
        first = date(year, month, 1)
        next_m = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        total = 0.0
        cur = first
        while cur < next_m:
            shifts = self._get_shift_rules_for_employee_on_date(employee, cur)
            total += sum((ht - hf) for hf, ht in shifts) if shifts else 0.0
            cur += timedelta(days=1)
        return total

    def _fine_rate_per_hour(self, employee, contract, day_date, month_sched_cache, scheduled_today=0.0):
        if not contract:
            return 0.0

        wage_type = (getattr(contract, "wage_type", "") or "monthly").strip().lower()

        # Hourly flexible: no penalty as per your rule
        if wage_type == "hourly":
            return 0.0

        # Late fine not applicable => no rate
        if not bool(getattr(contract, "is_latefine_applicable", False)):
            return 0.0

        mode = (getattr(contract, "apply_late_fine", "") or "").strip().lower()

        # Fixed per hour
        if mode == "fixed":
            return float(getattr(contract, "late_fine_rate", 0.0) or 0.0)

        # Wage-based
        if wage_type == "daily":
            daily_wage = float(getattr(contract, "daily_wage", 0.0) or 0.0)
            sched = float(scheduled_today or 0.0)
            return (daily_wage / sched) if (daily_wage > 0 and sched > 0) else 0.0

        # Default monthly
        wage = float(getattr(contract, "wage", 0.0) or 0.0)
        if wage <= 0:
            return 0.0

        key = (employee.id, day_date.year, day_date.month)
        if key not in month_sched_cache:
            month_sched_cache[key] = self._monthly_scheduled_hours(employee, day_date.year, day_date.month)

        sched = month_sched_cache[key]
        return (wage / sched) if sched > 0 else 0.0


    def _last_attendance(self, day_att):
        return day_att.sorted(key=lambda a: ((a.check_out or a.check_in), a.id))[-1] if day_att else False


    def _subtract_intervals(self, intervals, subtracts):
        """intervals/subtracts: list of (start_dt, end_dt) tz-aware datetimes"""
        out = []
        for s, e in intervals:
            parts = [(s, e)]
            for ls, le in subtracts:
                new_parts = []
                for ps, pe in parts:
                    # no overlap
                    if le <= ps or ls >= pe:
                        new_parts.append((ps, pe))
                        continue
                    # left remainder
                    if ls > ps:
                        new_parts.append((ps, ls))
                    # right remainder
                    if le < pe:
                        new_parts.append((le, pe))
                parts = new_parts
            out.extend([(ps, pe) for ps, pe in parts if pe > ps])
        return out

    def _get_validated_leave_intervals_local(self, employee, tzname, tz, d):
        """
        Returns validated hr.leave intervals overlapping local day 'd' in tz-aware local datetimes.
        """
        Leave = self.env["hr.leave"].sudo()

        day_start_local = tz.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
        day_end_local = day_start_local + timedelta(days=1)

        # Odoo stores datetimes as naive UTC; convert to naive UTC for domains
        day_start_utc = day_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        day_end_utc = day_end_local.astimezone(pytz.UTC).replace(tzinfo=None)

        leaves = Leave.search([
            ("employee_id", "=", employee.id),
            ("state", "=", "validate"),
            ("date_from", "<", day_end_utc),
            ("date_to", ">", day_start_utc),
        ])

        intervals = []
        for lv in leaves:
            if not lv.date_from or not lv.date_to:
                continue
            s_utc = max(lv.date_from, day_start_utc)
            e_utc = min(lv.date_to, day_end_utc)
            if e_utc <= s_utc:
                continue

            s_loc = self._ctx_ts(tzname, s_utc)
            e_loc = self._ctx_ts(tzname, e_utc)

            if s_loc.tzinfo is None:
                s_loc = tz.localize(s_loc)
            if e_loc.tzinfo is None:
                e_loc = tz.localize(e_loc)

            intervals.append((s_loc, e_loc))

        return sorted(intervals, key=lambda x: x[0])


    # ===========================
    # MAIN: recompute
    # ===========================
    @api.model
    def bambus_recompute_range(self, employee_ids, date_start, date_end):
        Attendance = self.env["hr.attendance"].sudo()
        Param = self.env["ir.config_parameter"].sudo()
        Overtime = self.sudo()

        weekend_days = []
        if Param.get_param('hr_payroll.weekend_mon') == 'True': weekend_days.append(0)
        if Param.get_param('hr_payroll.weekend_tue') == 'True': weekend_days.append(1)
        if Param.get_param('hr_payroll.weekend_wed') == 'True': weekend_days.append(2)
        if Param.get_param('hr_payroll.weekend_thu') == 'True': weekend_days.append(3)
        if Param.get_param('hr_payroll.weekend_fri') == 'True': weekend_days.append(4)
        if Param.get_param('hr_payroll.weekend_sat') == 'True': weekend_days.append(5)
        if Param.get_param('hr_payroll.weekend_sun') == 'True': weekend_days.append(6)

        # safe flags (won't break if fields are not yet added)
        has_fine_hours = "bambus_fine_hours" in Attendance._fields
        has_fine_amount = "bambus_fine_amount" in Attendance._fields
        has_late = "bambus_late_minutes" in Attendance._fields
        has_sched = "bambus_scheduled_hours" in Attendance._fields
        has_short = "bambus_shortfall_hours" in Attendance._fields
        has_early = "bambus_early_leave_minutes" in Attendance._fields
        has_gap = "bambus_gap_minutes" in Attendance._fields


        start_date = fields.Date.to_date(date_start)
        end_date = fields.Date.to_date(date_end)
        days = self._date_list(start_date, end_date)

        employees = self.env["hr.employee"].browse(employee_ids).exists()
        month_sched_cache = {}

        for emp in employees:
            company = emp.company_id
            ot_mode = company.bambus_ot_mode  # 'odoo' or 'custom'

            # fetch a small window (fast + safe)
            atts = Attendance.search([
                ("employee_id", "=", emp.id),
                ("check_in", ">=", fields.Datetime.to_datetime(start_date) - timedelta(days=1)),
                ("check_in", "<=", fields.Datetime.to_datetime(end_date) + timedelta(days=1)),
            ])

            # group by local date using employee/calendar tz
            by_date = defaultdict(lambda: Attendance.browse())
            contract0 = self._get_contract_on_date(emp, start_date)
            tzname0 = self._get_calendar_tz(emp, contract0)

            for a in atts:
                if not a.check_in:
                    continue
                d_local = self._ctx_ts(tzname0, a.check_in).date()
                if start_date <= d_local <= end_date:
                    by_date[d_local] |= a

            for d in days:
                day_att = by_date.get(d, Attendance.browse())
                if not day_att:
                    continue  # no absence fine as per your request

                contract = self._get_contract_on_date(emp, d)
                tzname = self._get_calendar_tz(emp, contract)
                tz = pytz.timezone(tzname)

                wage_type = (getattr(contract, "wage_type", "") or "monthly").strip().lower() if contract else "monthly"

                # --------------------------
                # compute schedule (effective) for storing scheduled/shortfall
                # --------------------------
                shifts = self._get_shift_rules_for_employee_on_date(emp, d)
                bounds = self._shift_bounds_local(tz, d, shifts) if shifts else []

                leave_intervals = self._get_validated_leave_intervals_local(emp, tzname, tz, d) if bounds else []

                effective_bounds = []
                per_shift_effective = []
                for b in bounds:
                    segs = self._subtract_intervals([b], leave_intervals)
                    per_shift_effective.append(segs)
                    effective_bounds.extend(segs)

                scheduled = sum((e - s).total_seconds() for s, e in effective_bounds) / 3600.0
                worked = sum(day_att.mapped("worked_hours")) if day_att else 0.0

                # ---> NEW FIX: Save the true schedule length (usually 8.0) before zeroing it <---
                base_shift_hours = scheduled if scheduled > 0 else 8.0

                # ---> NEW FIX: FORCE GLOBAL WEEKENDS TO BE OFF-DAYS <---
                if d.weekday() in weekend_days:
                    scheduled = 0.0

                # minute-rounded storage (Option B style)
                scheduled_minutes = int(round((scheduled or 0.0) * 60.0))
                scheduled_store = scheduled_minutes / 60.0

                # keep shortfall aligned with fine (both represent total deficit)
                shortfall_minutes = int(round(max(0.0, (scheduled or 0.0) - (worked or 0.0)) * 60.0))
                shortfall_store = shortfall_minutes / 60.0
                # later, we ensure fine_minutes == shortfall_minutes through the split


                # If no schedule => clear everything (including scheduled/shortfall)
                # This naturally includes weekends (no shift) and festivals/holidays (shift zeroed by leave)
                if scheduled <= 0:
                    clear_vals = {}
                    if has_fine_hours:
                        clear_vals["bambus_fine_hours"] = 0.0
                    if has_fine_amount:
                        clear_vals["bambus_fine_amount"] = 0.0
                    if has_late:
                        clear_vals["bambus_late_minutes"] = 0
                    if has_sched:
                        clear_vals["bambus_scheduled_hours"] = 0.0
                    if has_short:
                        clear_vals["bambus_shortfall_hours"] = 0.0

                    if clear_vals:
                        day_att.with_context(bambus_skip_recompute=True).write(clear_vals)

                    if ot_mode == "custom":
                        # 1. Check if weekend/festival OT is enabled in settings
                        allow_weekend_ot = Param.get_param("hr_payroll.ot_for_weekend_and_festival") == "True"
                        
                        # 2. Check if the employee's contract allows OT
                        allow_ot = bool(
                            contract
                            and wage_type in ("daily", "monthly")
                            and getattr(contract, "is_overtime_allowed", False)
                        )

                        # 3. If both are True, calculate OT ONLY for time worked beyond the standard shift
                        duration_to_store = 0.0
                        if allow_weekend_ot and allow_ot:
                            # Use the actual base shift (8.0) instead of the 6.0 threshold
                            duration_to_store = max(0.0, worked - base_shift_hours)

                        base_ot = Overtime.search([
                            ("employee_id", "=", emp.id),
                            ("date", "=", d),
                            ("adjustment", "=", False),
                        ], limit=1)
                        
                        if not base_ot:
                            # Create the OT record if they worked and it's allowed
                            if duration_to_store > 0:
                                base_ot = Overtime.create({
                                    "employee_id": emp.id,
                                    "date": d,
                                    "adjustment": False,
                                    "duration": duration_to_store,
                                })
                        else:
                            # Update existing record (will reset to 0 if OT is not allowed)
                            base_ot.write({"duration": duration_to_store})
                            
                        day_att._compute_overtime_hours()

                    continue

                # ---------------------------------------------------------
                # HOURLY (flexible): paid for worked hours, no penalty, no OT
                # (still stores scheduled/shortfall for reporting)
                # ---------------------------------------------------------
                if wage_type == "hourly":
                    # clear day values first (keep only last record)
                    clear_vals = {}
                    if has_fine_hours:
                        clear_vals["bambus_fine_hours"] = 0.0
                    if has_fine_amount:
                        clear_vals["bambus_fine_amount"] = 0.0
                    if has_late:
                        clear_vals["bambus_late_minutes"] = 0
                    if has_sched:
                        clear_vals["bambus_scheduled_hours"] = 0.0
                    if has_short:
                        clear_vals["bambus_shortfall_hours"] = 0.0
                    if clear_vals:
                        day_att.with_context(bambus_skip_recompute=True).write(clear_vals)

                    last = self._last_attendance(day_att)
                    if last:
                        last_vals = {}
                        if has_sched:
                            last_vals["bambus_scheduled_hours"] = scheduled_store
                        if has_short:
                            last_vals["bambus_shortfall_hours"] = shortfall_store
                        if last_vals:
                            last.with_context(bambus_skip_recompute=True).write(last_vals)

                    # Hourly = paid per worked hour => NO schedule-based overtime.
                    # Force the day's base overtime to 0 so the attendance stops
                    # showing native "Over Time / Extra Hours" (worked - schedule).
                    # Done for BOTH ot modes: the default "odoo" mode would
                    # otherwise leave worked-minus-schedule overtime on the record,
                    # which is exactly the number that was surpassing the limit.
                    base_ot = Overtime.search([
                        ("employee_id", "=", emp.id),
                        ("date", "=", d),
                        ("adjustment", "=", False),
                    ], limit=1)
                    if not base_ot:
                        base_ot = Overtime.create({
                            "employee_id": emp.id,
                            "date": d,
                            "adjustment": False,
                            "duration": 0.0,
                        })
                    else:
                        base_ot.write({"duration": 0.0})
                    day_att._compute_overtime_hours()

                    continue

                # --------------------------
                # Strict schedule employees (monthly/daily)
                # --------------------------

                # build checkins
                checkins = []
                for a in day_att:
                    if a.check_in:
                        ci = self._ctx_ts(tzname, a.check_in)
                        if ci.tzinfo is None:
                            ci = tz.localize(ci)
                        checkins.append(ci)
                checkins.sort()

                # late computed vs effective start (after leave), once per shift
                late_raw = 0.0
                for segs in per_shift_effective:
                    if not segs:
                        continue
                    eff_start = segs[0][0]
                    ci_in_eff = next(
                        (ci for ci in checkins if any(ss <= ci <= ee for ss, ee in segs)),
                        None
                    )
                    if ci_in_eff and ci_in_eff > eff_start:
                        late_raw += (ci_in_eff - eff_start).total_seconds() / 3600.0

                # Option B: round late to whole minutes
                late_minutes = int(round((late_raw or 0.0) * 60.0))
                late_raw = late_minutes / 60.0

                # ---- OT (worked time after scheduled end only; excludes gaps)
                sched_end = max([e for _, e in effective_bounds], default=False)

                # ---- Early leave minutes (only when employee finishes before schedule end)
                early_leave_minutes = 0
                last_co = None
                for a in day_att:
                    if a.check_out:
                        co = self._ctx_ts(tzname, a.check_out)
                        if co.tzinfo is None:
                            co = tz.localize(co)
                        if (last_co is None) or (co > last_co):
                            last_co = co

                if sched_end and last_co and last_co < sched_end:
                    early_leave_minutes = int(round((sched_end - last_co).total_seconds() / 60.0))

                gap_minutes = max(0, int(shortfall_minutes or 0) - int(late_minutes or 0) - int(early_leave_minutes or 0))

                ot_hours = 0.0
                if sched_end:
                    for a in day_att:
                        if not a.check_in or not a.check_out:
                            continue

                        ci = self._ctx_ts(tzname, a.check_in)
                        co = self._ctx_ts(tzname, a.check_out)
                        if ci.tzinfo is None:
                            ci = tz.localize(ci)
                        if co.tzinfo is None:
                            co = tz.localize(co)

                        start = max(ci, sched_end)
                        if co > start:
                            ot_hours += (co - start).total_seconds() / 3600.0

                # Option B rounding for OT too
                # Option B rounding for OT too
                ot_minutes = int(round((ot_hours or 0.0) * 60.0))
                
                # Fetch "Tolerance Time In Favor Of Company" from settings
                company_tolerance = int(getattr(company, 'overtime_company_threshold', 0))
                
                # 1. No OT if they didn't even complete their base scheduled hours
                if worked < scheduled:
                    ot_minutes = 0
                # 2. No OT if the extra minutes fall within the company tolerance
                elif ot_minutes <= company_tolerance:
                    ot_minutes = 0

                ot_hours = ot_minutes / 60.0

                # ---- Fine split (simple + always matched)
                scheduled_minutes = int(round((scheduled or 0.0) * 60.0))
                worked_minutes = int(round((worked or 0.0) * 60.0))


                half_day_threshold = float(Param.get_param("hr_payroll.half_day_hours", 4) or 4)
                full_day_threshold = float(Param.get_param("hr_payroll.full_day_hours", 8) or 8)

                # Ensure late_minutes and early_leave_minutes are integers
                late_minutes = int(late_minutes or 0)
                early_leave_minutes = int(early_leave_minutes or 0)

                # Calculate the actual deficit against the full day schedule
                actual_deficit_minutes = max(0, scheduled_minutes - worked_minutes)

                # APPLY WORK HOUR RULES THRESHOLDS
                if half_day_threshold <= worked < full_day_threshold:
                    # Employee completed a valid half-day. 
                    early_leave_minutes = 0
                    gap_minutes = 0
                    
                    # Calculate deficit against a 4-hour half-day schedule
                    half_day_sched_mins = scheduled_minutes / 2
                    half_deficit = max(0, half_day_sched_mins - worked_minutes)
                    
                    # Cap late minutes so they are forgiven if they worked 4+ hours
                    late_minutes = int(min(late_minutes, half_deficit))
                    deficit_minutes = late_minutes 
                    
                elif worked >= full_day_threshold:
                    # Employee completed a full day. Forgive early leave and gap.
                    early_leave_minutes = 0
                    gap_minutes = 0
                    
                    # Cap late minutes by the actual deficit. 
                    # If worked >= scheduled, actual_deficit_minutes is 0, erasing the late fine.
                    late_minutes = int(max(late_minutes, actual_deficit_minutes))
                    deficit_minutes = late_minutes
                    
                else:
                    # Standard calculation: didn't meet thresholds, penalize against full schedule
                    deficit_minutes = actual_deficit_minutes
                    late_minutes = int(min(late_minutes, deficit_minutes))
                    early_leave_minutes = int(min(early_leave_minutes, deficit_minutes - late_minutes))
                    gap_minutes = max(0, deficit_minutes - late_minutes - early_leave_minutes)

                # fine is the sum of the 3 buckets (matches deficit)
                fine_minutes = late_minutes + early_leave_minutes + gap_minutes
                fine_hours = fine_minutes / 60.0


                # ---------------------------------------------------------
                # Fine applicability + rate (fixed / wage_based)
                # ---------------------------------------------------------
                fine_amount = 0.0
                if not (contract and bool(getattr(contract, "is_latefine_applicable", False))):
                    fine_hours = 0.0
                    fine_amount = 0.0
                else:
                    mode = (getattr(contract, "apply_late_fine", "") or "").strip().lower()
                    fine_rate = 0.0

                    if mode == "fixed":
                        fine_rate = float(getattr(contract, "late_fine_rate", 0.0) or 0.0)
                    else:
                        if wage_type == "daily":
                            daily_wage = float(getattr(contract, "daily_wage", 0.0) or 0.0)
                            fine_rate = (daily_wage / scheduled) if (daily_wage > 0 and scheduled > 0) else 0.0
                        else:
                            wage = float(getattr(contract, "wage", 0.0) or 0.0)
                            if wage > 0:
                                key = (emp.id, d.year, d.month)
                                if key not in month_sched_cache:
                                    month_sched_cache[key] = self._monthly_scheduled_hours(emp, d.year, d.month)
                                month_sched = month_sched_cache[key]
                                fine_rate = (wage / month_sched) if month_sched > 0 else 0.0

                    fine_amount = fine_hours * fine_rate if fine_rate > 0 else 0.0
                    if mode == "fixed":
                        fine_amount = fine_minutes * fine_rate if fine_rate > 0 else 0.0
                    # Limits, prevent overcharge
                    if wage_type == "daily":
                        fine_amount = min(fine_amount, contract.daily_wage)

                    currency = emp.company_id.currency_id
                    if currency:
                        fine_amount = currency.round(fine_amount)

                # ---- Custom mode writes OT duration so hr.attendance.overtime_hours shows it
                if ot_mode == "custom":
                    allow_ot = bool(
                        contract
                        and wage_type in ("daily", "monthly")
                        and getattr(contract, "is_overtime_allowed", False)
                    )
                    duration_to_store = ot_hours if allow_ot else 0.0

                    base_ot = Overtime.search([
                        ("employee_id", "=", emp.id),
                        ("date", "=", d),
                        ("adjustment", "=", False),
                    ], limit=1)

                    if not base_ot:
                        base_ot = Overtime.create({
                            "employee_id": emp.id,
                            "date": d,
                            "adjustment": False,
                            "duration": 0.0,
                        })

                    base_ot.write({"duration": duration_to_store})
                    day_att._compute_overtime_hours()

                # ---- Store day metrics only on last attendance of the day
                clear_vals = {}
                if has_fine_hours:
                    clear_vals["bambus_fine_hours"] = 0.0
                if has_fine_amount:
                    clear_vals["bambus_fine_amount"] = 0.0
                if has_late:
                    clear_vals["bambus_late_minutes"] = 0
                if has_sched:
                    clear_vals["bambus_scheduled_hours"] = 0.0
                if has_short:
                    clear_vals["bambus_shortfall_hours"] = 0.0
                if has_early:
                    clear_vals["bambus_early_leave_minutes"] = 0
                if has_gap:
                    clear_vals["bambus_gap_minutes"] = 0

                if clear_vals:
                    day_att.with_context(bambus_skip_recompute=True).write(clear_vals)

                last = self._last_attendance(day_att)
                if last:
                    last_vals = {}
                    if has_late:
                        last_vals["bambus_late_minutes"] = int(late_minutes or 0)
                    if has_fine_hours:
                        last_vals["bambus_fine_hours"] = fine_hours
                    if has_fine_amount:
                        last_vals["bambus_fine_amount"] = fine_amount
                    if has_sched:
                        last_vals["bambus_scheduled_hours"] = scheduled_store
                    if has_short:
                        last_vals["bambus_shortfall_hours"] = shortfall_store
                    if has_early:
                        last_vals["bambus_early_leave_minutes"] = int(early_leave_minutes or 0)
                    if has_gap:
                        last_vals["bambus_gap_minutes"] = int(gap_minutes or 0)

                    if last_vals:
                        last.with_context(bambus_skip_recompute=True).write(last_vals)
