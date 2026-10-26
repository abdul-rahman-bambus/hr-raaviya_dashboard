# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta, time
import pytz
from collections import defaultdict
import logging


_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    @api.depends(
        "employee_id", "contract_id", "date_from", "date_to",
        "contract_id.hourly_wage_hour_limit",
        "employee_id.attendance_automation_template_id.hourly_pay_use_template_limit",
        "employee_id.attendance_automation_template_id.hourly_wage_hour_limit",
        "employee_id.attendance_automation_template_id.active",
        "employee_id.attendance_automation_template_id.date_from",
        "employee_id.attendance_automation_template_id.date_to",
        "employee_id.company_id.attendance_automation_template_id.hourly_pay_use_template_limit",
        "employee_id.company_id.attendance_automation_template_id.hourly_wage_hour_limit",
        "employee_id.company_id.attendance_automation_template_id.active",
        "employee_id.company_id.attendance_automation_template_id.date_from",
        "employee_id.company_id.attendance_automation_template_id.date_to",
    )
    def _compute_worker_hours(self):
        return super()._compute_worker_hours()

    def action_compute_sheet(self):
        """Refresh attendance buckets before evaluating payroll salary rules."""
        self = self.filtered(lambda record: record.state in ('draft', 'verify'))
        if not self:
            return True
        overtime_model = self.env["hr.attendance.overtime"].sudo()
        for slip in self:
            if slip.employee_id and slip.date_from and slip.date_to:
                overtime_model.bambus_recompute_range(
                    slip.employee_id.ids, slip.date_from, slip.date_to
                )
        # Refresh before statistics AND generated worked-day rows are built;
        # the base payroll layer also supports standalone custom_hr_payroll.
        self.filtered(lambda slip: slip.contract_id.wage_type == 'hourly')._compute_worker_hours()
        self._compute_all_stats()
        for slip in self.filtered(lambda record: record.state in ('draft', 'verify')):
            if not (slip.employee_id and slip.contract_id and slip.date_from and slip.date_to):
                continue
            # Core payroll only refreshes worked-day lines on form onchanges.
            # Compute Sheet must refresh them too after attendance corrections.
            days = slip.get_worked_day_lines(slip.contract_id, slip.date_from, slip.date_to)
            managed_codes = {'WORK100', 'DAYSWORKED', 'WEEKEND', 'HOLIDAYS',
                             'PAID_WEEKLY_OFF', 'PAID_PUBLIC_HOLIDAY'}
            managed_codes.update(self.env['hr.leave.type'].search([]).mapped('code'))
            managed_codes.update(row['code'] for row in days)
            slip.worked_days_line_ids.filtered(lambda row: row.code in managed_codes).unlink()
            slip.write({'worked_days_line_ids': [(0, 0, row) for row in days]})
        return super().action_compute_sheet()

    days_excl_weekend_holidays = fields.Float("Scheduled Regular Days", compute="_compute_all_stats", store=True)
    total_working_days = fields.Float("Regular Worked Days", compute="_compute_all_stats", store=True)
    total_worked_hours_excl_ot = fields.Float("Regular Worked Hours (Excluding OT)", compute="_compute_all_stats", store=True)
    total_validated_overtime = fields.Float("Overtime", compute="_compute_all_stats", store=True)
    total_late_login_minutes = fields.Float("Late Login Hours", compute="_compute_all_stats", store=True)
    total_late_after_grace = fields.Float("Late after grace", compute="_compute_all_stats", store=True)

    weekend_days = fields.Float("Weekly-off Calendar Days", compute="_compute_all_stats", store=True)
    weekend_worked = fields.Float("Weekly-off Worked Days", compute="_compute_all_stats", store=True)
    weekend_hours = fields.Float("Weekly-off Worked Hours", compute="_compute_all_stats", store=True)


    holiday_days = fields.Float("Public Holiday Calendar Days", compute="_compute_all_stats", store=True)
    holiday_worked = fields.Float("Public Holiday Worked Days", compute="_compute_all_stats", store=True)
    holiday_hours = fields.Float("Public Holiday Worked Hours", compute="_compute_all_stats", store=True)

    total_overtime_amount = fields.Float(string="Overtime Amount", compute="_compute_all_stats", store=True)
    total_public_holiday_amount = fields.Float(
        string="Public Holiday Amount", compute="_compute_all_stats", store=True
    )
    total_fine_hours = fields.Float(string="Fine Hours", compute="_compute_all_stats", store=True)
    total_fine_amount = fields.Float(string="Fine Amount", compute="_compute_all_stats", store=True)


    total_scheduled_hours = fields.Float(string="Scheduled Hours", compute="_compute_all_stats", store=True)
    total_shortfall_hours = fields.Float(string="Shortfall Hours", compute="_compute_all_stats", store=True)

    total_late_hours = fields.Float(string="Late Hours", compute="_compute_all_stats", store=True)
    total_early_leave_hours = fields.Float(string="Early Leave Hours", compute="_compute_all_stats", store=True)
    total_gap_hours = fields.Float(string="Gap Hours", compute="_compute_all_stats", store=True)
    total_fine_after_grace_hours = fields.Float(string="Fine After Grace", compute="_compute_all_stats", store=True)


    uses_template_regular_pay = fields.Boolean(compute="_compute_all_stats", store=True)
    paid_weekly_off_days = fields.Float(string="Paid Weekly-off Days", compute="_compute_all_stats", store=True)
    paid_weekly_off_amount = fields.Float(string="Paid Weekly-off Amount", compute="_compute_all_stats", store=True)
    paid_public_holiday_days = fields.Float(string="Paid Public Holiday Days", compute="_compute_all_stats", store=True)
    paid_public_holiday_amount = fields.Float(string="Paid Public Holiday Amount", compute="_compute_all_stats", store=True)
    # Worked-day rows already account for these fractions. Only the remaining
    # paid-day credit belongs in the separate PAID_* worked-day rows.
    paid_weekly_off_worked_days = fields.Float(compute="_compute_all_stats", store=True)
    paid_public_holiday_worked_days = fields.Float(compute="_compute_all_stats", store=True)
    withheld_weekly_off_worked_days = fields.Float(compute="_compute_all_stats", store=True)
    withheld_public_holiday_worked_days = fields.Float(compute="_compute_all_stats", store=True)
    total_regular_pay_amount = fields.Float(string="Regular Pay Amount", compute="_compute_all_stats", store=True)

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

    def _get_public_holiday_dates(self, contract, date_from, date_to, tzname):
        """Return schedule-specific and database-wide public holiday dates."""
        calendar = contract.resource_calendar_id if contract else False
        domain = [
            ("resource_id", "=", False),
            ("date_from", "<=", fields.Datetime.to_string(
                datetime.combine(date_to, time.max)
            )),
            ("date_to", ">=", fields.Datetime.to_string(
                datetime.combine(date_from, time.min)
            )),
        ]
        if calendar:
            domain = [
                ("resource_id", "=", False),
                "|",
                ("calendar_id", "=", calendar.id),
                ("calendar_id", "=", False),
                *domain[1:],
            ]
        else:
            domain.append(("calendar_id", "=", False))
        leaves = self.env["resource.calendar.leaves"].sudo().search(domain)
        dates = set()
        for leave in leaves:
            if not (leave.date_from and leave.date_to):
                continue
            context = self.with_context(tz=tzname)
            start = fields.Datetime.context_timestamp(context, leave.date_from).date()
            end = fields.Datetime.context_timestamp(context, leave.date_to).date()
            current = start
            while current <= end:
                if date_from <= current <= date_to:
                    dates.add(current)
                current += timedelta(days=1)
        return dates


    # ---------------------------
    # Main compute
    # ---------------------------
    @api.depends(
        "date_from", "date_to", "employee_id", "contract_id",
        "contract_id.wage", "contract_id.wage_type", "contract_id.daily_wage", "contract_id.hourly_rate",
        "contract_id.date_start", "contract_id.date_end", "contract_id.resource_calendar_id.hours_per_day",
        "total_worker_hours",
        "employee_id.paid_day_decision_ids",
        "employee_id.paid_day_decision_ids.action",
        "employee_id.attendance_ids", "employee_id.attendance_ids.check_in", "employee_id.attendance_ids.check_out",
        "employee_id.attendance_ids.worked_hours", "employee_id.attendance_ids.overtime_hours", "employee_id.attendance_ids.bambus_scheduled_hours",
        "employee_id.attendance_ids.bambus_shortfall_hours",
        "employee_id.attendance_automation_template_id.half_day_hours",
        "employee_id.attendance_automation_template_id.full_day_basis",
        "employee_id.attendance_automation_template_id.full_day_hours",
        "employee_id.attendance_automation_template_id.reviewed_exception_day_pay",
        "employee_id.attendance_automation_template_id.partial_attendance_salary_treatment",
        "employee_id.company_id.attendance_automation_template_id.half_day_hours",
        "employee_id.company_id.attendance_automation_template_id.full_day_basis",
        "employee_id.company_id.attendance_automation_template_id.full_day_hours",
        "employee_id.company_id.attendance_automation_template_id.reviewed_exception_day_pay",
        "employee_id.company_id.attendance_automation_template_id.partial_attendance_salary_treatment",
        "employee_id.attendance_automation_template_id.active",
        "employee_id.attendance_automation_template_id.date_from",
        "employee_id.attendance_automation_template_id.date_to",
        "employee_id.attendance_automation_template_id.weekly_off_source",
        "employee_id.attendance_automation_template_id.monthly_paid_weekly_off",
        "employee_id.attendance_automation_template_id.monthly_paid_public_holiday",
        "employee_id.attendance_automation_template_id.weekly_off_monday",
        "employee_id.attendance_automation_template_id.weekly_off_tuesday",
        "employee_id.attendance_automation_template_id.weekly_off_wednesday",
        "employee_id.attendance_automation_template_id.weekly_off_thursday",
        "employee_id.attendance_automation_template_id.weekly_off_friday",
        "employee_id.attendance_automation_template_id.weekly_off_saturday",
        "employee_id.attendance_automation_template_id.weekly_off_sunday",
        "employee_id.company_id.attendance_automation_template_id.active",
        "employee_id.company_id.attendance_automation_template_id.date_from",
        "employee_id.company_id.attendance_automation_template_id.date_to",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_source",
        "employee_id.company_id.attendance_automation_template_id.monthly_paid_weekly_off",
        "employee_id.company_id.attendance_automation_template_id.monthly_paid_public_holiday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_monday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_tuesday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_wednesday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_thursday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_friday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_saturday",
        "employee_id.company_id.attendance_automation_template_id.weekly_off_sunday",
    )
    def _compute_all_stats(self):
        Param = self.env["ir.config_parameter"].sudo()

        half_day_hrs = float(Param.get_param("hr_payroll.half_day_hours", 4) or 4)
        full_day_hrs = float(Param.get_param("hr_payroll.full_day_hours", 8) or 8)
        grace_minutes = int(Param.get_param("custom_hr_payroll.late_login_grace_minutes", 0) or 0)

        Attendance = self.env["hr.attendance"].sudo()
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
            slip.withheld_weekly_off_worked_days = 0.0
            slip.withheld_public_holiday_worked_days = 0.0

            slip.uses_template_regular_pay = False
            slip.paid_weekly_off_days = 0.0
            slip.paid_weekly_off_amount = 0.0
            slip.paid_public_holiday_days = 0.0
            slip.paid_public_holiday_amount = 0.0
            slip.paid_weekly_off_worked_days = 0.0
            slip.paid_public_holiday_worked_days = 0.0
            slip.total_regular_pay_amount = 0.0
            slip.total_overtime_amount = 0.0
            slip.total_public_holiday_amount = 0.0
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

            tzname = (
                contract.resource_calendar_id.tz
                if contract and contract.resource_calendar_id and contract.resource_calendar_id.tz
                else self.env.user.tz or "UTC"
            )
            public_holidays = slip._get_public_holiday_dates(
                contract, slip.date_from, slip.date_to, tzname
            )
            total_days = (slip.date_to - slip.date_from).days + 1
            weekly_off_dates = {
                slip.date_from + timedelta(days=i) for i in range(total_days)
                if emp._is_attendance_weekly_off(slip.date_from + timedelta(days=i))
            }
            slip.weekend_days = float(sum(
                1 for i in range(total_days)
                if (slip.date_from + timedelta(days=i)) in weekly_off_dates
                and (slip.date_from + timedelta(days=i)) not in public_holidays
            ))
            slip.holiday_days = float(len(public_holidays))
            slip.days_excl_weekend_holidays = float(sum(
                1 for i in range(total_days)
                if (slip.date_from + timedelta(days=i)) not in weekly_off_dates
                and (slip.date_from + timedelta(days=i)) not in public_holidays
            ))

            # Worker hourly: simple totals from attendances (no OT/fine/late)
            if getattr(emp, "employee_type", False) == "worker" and contract and getattr(contract, "wage_type", "") == "hourly":
                # Billable hours are capped per LOCAL day at the contract's
                # hourly_wage_hour_limit ("cannot be billed beyond this time").
                # Raw attendance worked_hours are left authentic.
                slip.total_scheduled_hours = 0.0
                slip.total_shortfall_hours = 0.0
                continue

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

            # HR-saved daily values are authoritative for payroll.  The legacy
            # technical state value "approved" is retained for upgrade safety;
            # functionally it means that HR saved the attendance correction.
            approved_lines_by_day = {}
            if "bambus.hr.attendance.sheet.line" in self.env:
                approved_lines = self.env["bambus.hr.attendance.sheet.line"].sudo().search([
                    ("employee_id", "=", emp.id),
                    ("date", ">=", slip.date_from),
                    ("date", "<=", slip.date_to),
                    "|",
                    ("overtime_state", "in", ("approved", "rejected")),
                    ("fine_state", "in", ("approved", "rejected")),
                ])
                approved_lines_by_day = {line.date: line for line in approved_lines}

            has_ot_amount = ("bambus_overtime_amount" in Attendance._fields)
            has_fine = ("bambus_fine_hours" in Attendance._fields and "bambus_fine_amount" in Attendance._fields)
            has_late = ("bambus_late_minutes" in Attendance._fields)
            has_sched = ("bambus_scheduled_hours" in Attendance._fields)
            has_short = ("bambus_shortfall_hours" in Attendance._fields)
            has_early = ("bambus_early_leave_minutes" in Attendance._fields)
            has_gap = ("bambus_gap_minutes" in Attendance._fields)


            paid_leaves = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', emp.id), ('state', '=', 'validate'),
                ('holiday_status_id.unpaid', '=', False),
                ('request_date_from', '<=', slip.date_to), ('request_date_to', '>=', slip.date_from),
            ])
            late_by_month = defaultdict(int)
            legacy_late_by_month = defaultdict(int)
            template_late_minutes = 0

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

                approval_line = approved_lines_by_day.get(d)
                if approval_line and approval_line.overtime_state == "approved":
                    ot = approval_line.overtime_hours or 0.0
                    ot_amount = approval_line.overtime_amount or 0.0
                elif approval_line and approval_line.overtime_state == "rejected":
                    ot = 0.0
                    ot_amount = 0.0

                if contract.wage_type == 'hourly' or (emp._get_attendance_automation_template(d) and not (approval_line and approval_line.overtime_state == 'approved')):
                    # Detection is a proposal, never an earning before HR approval.
                    ot = 0.0
                    ot_amount = 0.0

                # last-attendance values (stored values only)
                scheduled_today = 0.0
                if day_att:
                    last = day_att.sorted(key=lambda a: ((a.check_out or a.check_in), a.id))[-1]
                    if has_sched:
                        scheduled_today = float(last.bambus_scheduled_hours or 0.0)

                automation = emp._get_attendance_automation_template(d)
                if automation:
                    slip.uses_template_regular_pay = True
                # Resolve day targets from the same template used by detection.
                if scheduled_today <= 0:
                    scheduled_today = (
                        sum(end - start for start, end in emp._get_attendance_work_periods(d))
                        or automation.full_day_hours
                    ) if automation else float(full_day_hrs)
                half_day_target = (
                    automation.half_day_hours if automation else half_day_hrs
                )
                full_day_target = (
                    (sum(end - start for start, end in emp._get_attendance_work_periods(d))
                     or automation.full_day_hours)
                    if automation and automation.full_day_basis == "schedule"
                    else automation.full_day_hours if automation else full_day_hrs
                )

                # Match attendance reporting: compare actual hours with the
                # effective template threshold. Capping at the schedule can make
                # a higher fixed full-day target impossible to reach.
                day_fraction = emp._get_attendance_day_fraction(
                    d, worked, float(half_day_target), float(full_day_target))

                # ✅ for HOURS BUCKETS: keep regular base hours excluding OT (as you already do)
                base_hours = max(0.0, float(worked or 0.0) - float(ot or 0.0))


                is_weekend = d in weekly_off_dates and d not in public_holidays
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

                    # scheduled + shortfall from the last punch
                    if has_sched:
                        sched_h = float(last.bambus_scheduled_hours or 0.0)
                    if has_short:
                        short_h = float(last.bambus_shortfall_hours or 0.0)

                if approval_line and approval_line.fine_state == "approved":
                    fine_h = approval_line.fine_hours or 0.0
                    fine_amt = approval_line.fine_amount or 0.0
                elif approval_line and approval_line.fine_state == "rejected":
                    fine_h = 0.0
                    fine_amt = 0.0


                if automation and not (approval_line and approval_line.fine_state == 'approved'):
                    fine_h = fine_amt = 0.0

                # Normal pay and additional approved OT are independent buckets.
                # Paid Monthly special days retain normal credit even when worked.
                if (contract and contract.wage_type in ('daily', 'monthly')
                        and (not contract.date_start or d >= contract.date_start)
                        and (not contract.date_end or d <= contract.date_end)):
                    day_rate = contract.daily_wage if contract.wage_type == 'daily' else contract._get_monthly_daily_rate(d)
                    hours_per_day = contract.resource_calendar_id.hours_per_day or 8.0
                    withheld = ((is_weekend and emp._is_paid_day_withheld(d, 'weekly_off'))
                                or (is_holiday and emp._is_paid_day_withheld(d, 'public_holiday')))
                    if contract.wage_type == 'monthly' and withheld:
                        # A saved HR rejection removes normal special-day pay,
                        # including the worked-hours fallback; OT stays separate.
                        if is_holiday:
                            slip.withheld_public_holiday_worked_days += day_fraction
                        else:
                            slip.withheld_weekly_off_worked_days += day_fraction
                    elif is_weekend and emp._is_paid_attendance_weekly_off(d, contract):
                        slip.paid_weekly_off_days += 1
                        slip.paid_weekly_off_worked_days += day_fraction
                        slip.paid_weekly_off_amount += day_rate
                        slip.total_regular_pay_amount += day_rate
                    elif is_holiday and emp._is_paid_attendance_public_holiday(d, contract):
                        slip.paid_public_holiday_days += 1
                        slip.paid_public_holiday_worked_days += day_fraction
                        slip.paid_public_holiday_amount += day_rate
                        slip.total_regular_pay_amount += day_rate
                    elif is_weekend or is_holiday:
                        slip.total_regular_pay_amount += worked * day_rate / hours_per_day
                    else:
                        paid_fraction = 0.0
                        for leave in paid_leaves.filtered(lambda leave: leave.request_date_from <= d <= leave.request_date_to):
                            if leave.request_unit_hours:
                                paid_fraction += min(1.0, max(0.0, leave.request_hour_to - leave.request_hour_from) / (scheduled_today or hours_per_day))
                            else:
                                paid_fraction += 0.5 if leave.request_unit_half else 1.0
                        slip.total_regular_pay_amount += min(1.0, day_fraction + paid_fraction) * day_rate

                late_by_month[(d.year, d.month)] += late_mins
                if automation:
                    # Stored detection already applies per-session template grace.
                    template_late_minutes += late_mins
                else:
                    legacy_late_by_month[(d.year, d.month)] += late_mins

                if is_weekend:
                    slip.weekend_worked += day_fraction
                    slip.weekend_hours += base_hours + ot
                elif is_holiday:
                    slip.holiday_worked += day_fraction
                    slip.holiday_hours += base_hours + ot
                else:
                    slip.total_working_days += day_fraction
                    slip.total_worked_hours_excl_ot += base_hours

                # Public-holiday hours have their own Attendance Details bucket
                # and payslip earning classification. Do not duplicate them in
                # the regular-day Overtime total.
                if is_holiday:
                    slip.total_public_holiday_amount += ot_amount
                else:
                    slip.total_validated_overtime += ot
                    slip.total_overtime_amount += ot_amount
                slip.total_late_hours += late_mins / 60.0
                slip.total_early_leave_hours += early_mins / 60.0
                slip.total_gap_hours += gap_mins / 60.0
                slip.total_fine_hours += fine_h
                slip.total_fine_amount += fine_amt
                slip.total_scheduled_hours += sched_h
                slip.total_shortfall_hours += short_h

            if contract.wage_type == 'hourly':
                slip.total_regular_pay_amount = slip.total_worker_hours * contract.hourly_rate

            total_late_raw = sum(late_by_month.values())

            total_late_after = template_late_minutes + sum(
                max(0, minutes - grace_minutes) for minutes in legacy_late_by_month.values()
            )

            slip.total_late_login_minutes = total_late_raw / 60.0
            slip.total_late_after_grace = total_late_after / 60.0
            slip.total_fine_after_grace_hours = slip.total_late_after_grace


    def get_worked_day_lines(self, contracts, date_from, date_to):
        """Build special worked-day buckets from the effective template policy."""
        default_res = super(HrPayslip, self).get_worked_day_lines(contracts, date_from, date_to)
        # for each slip
        for slip in self:
            contract = slip.contract_id
            template_handles_holidays = False
            template_handles_weekly_off = False
            template_handles_partial_pay = False
            current_day = fields.Date.to_date(slip.date_from)
            last_day = fields.Date.to_date(slip.date_to)
            while slip.employee_id and current_day and last_day and current_day <= last_day:
                day_template = slip.employee_id._get_attendance_automation_template(
                    current_day
                )
                if (day_template and day_template.partial_attendance_salary_treatment == 'fine_only'
                        and slip.employee_id._fine_only_attendance_context(current_day) is not None):
                    template_handles_partial_pay = True
                if (
                    day_template
                    and slip.employee_id._is_attendance_weekly_off(current_day)
                    and day_template.overtime_enabled
                    and day_template.weekly_off_overtime_policy != "disabled"
                ):
                    template_handles_weekly_off = True
                    break
                current_day += timedelta(days=1)
            if slip.employee_id and slip.date_from and slip.date_to and slip.holiday_days:
                tzname = (
                    contract.resource_calendar_id.tz
                    if contract and contract.resource_calendar_id
                    else self.env.user.tz or "UTC"
                )
                public_holiday_dates = slip._get_public_holiday_dates(
                    contract, slip.date_from, slip.date_to, tzname
                )
                for holiday_date in public_holiday_dates:
                    template = slip.employee_id._get_attendance_automation_template(
                        holiday_date
                    )
                    if (
                        template
                        and template.public_holiday_overtime_policy != "disabled"
                    ):
                        template_handles_holidays = True
                        break

            # Use standard buckets when no template handles special dates or
            # partial attendance salary, and always for hourly contracts.
            if (not template_handles_weekly_off
                    and not template_handles_holidays and not template_handles_partial_pay and not slip.paid_weekly_off_days
                    and not slip.paid_public_holiday_days
                    and not slip.withheld_weekly_off_worked_days
                    and not slip.withheld_public_holiday_worked_days) \
                or contract.wage_type == 'hourly':

                return default_res

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

            # Credit rows top up eligible worked fractions to one paid day.
            # Withheld work retains actual hours/statistics, but contributes
            # zero normal paid days even when separately approved OT is paid.
            weekly_credit = slip.paid_weekly_off_days - (
                slip.paid_weekly_off_worked_days if template_handles_weekly_off else 0.0)
            holiday_credit = slip.paid_public_holiday_days - (
                slip.paid_public_holiday_worked_days if template_handles_holidays else 0.0)
            for code, name, days in (
                ('PAID_WEEKLY_OFF', 'Paid Weekly Off Credit', weekly_credit),
                ('PAID_PUBLIC_HOLIDAY', 'Paid Public Holiday Credit', holiday_credit),
            ):
                if days > 0:
                    res.append({
                        'name': name, 'sequence': 4, 'code': code,
                        'number_of_days': days, 'number_of_hours': 0.0,
                        'contract_id': contract.id,
                    })

            # WEEKEND worked ONLY IF enabled
            if slip.weekend_worked > 0 and template_handles_weekly_off:
                res.append({
                    'name': 'Weekend Working Days',
                    'sequence': 5,
                    'code': 'WEEKEND',
                    'number_of_days': max(0.0, slip.weekend_worked - slip.withheld_weekly_off_worked_days),
                    'number_of_hours': slip.weekend_hours,
                    'contract_id': contract.id,
                })

            # PUBLIC HOLIDAYS worked ONLY IF enabled
            if (
                slip.holiday_worked > 0
                and template_handles_holidays
            ):
                res.append({
                    'name': 'Public Holidays',
                    'sequence': 10,
                    'code': 'HOLIDAYS',
                    'number_of_days': max(0.0, slip.holiday_worked - slip.withheld_public_holiday_worked_days),
                    'number_of_hours': slip.holiday_hours,
                    'contract_id': contract.id,
                })

            leave_codes = set(self.env['hr.leave.type'].search([]).mapped('code')) - {False}
            res.extend(line for line in default_res if line['code'] in leave_codes)
            return res
