# -*- coding: utf-8 -*-
from odoo import models, fields
from datetime import datetime, timedelta, time
import math
import pytz
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)


class AttendanceXlsxReport(models.AbstractModel):
    _name = "report.attendance_custom_report.attendance_xlsx"
    _inherit = "report.report_xlsx.abstract"

    # ---------------- utilities ----------------
    def minutes_to_time(self, minutes):
        minutes = int(minutes or 0)
        hh, mm = divmod(minutes, 60)
        return f"{hh:02d}:{mm:02d}"

    def float_to_time(self, value):
        """Convert float hours into HH:MM."""
        if value is None:
            return "00:00"
        hours = int(math.floor(value))
        minutes = int(round((value - hours) * 60))
        if minutes >= 60:
            hours += minutes // 60
            minutes = minutes % 60
        return f"{hours:02d}:{minutes:02d}"

    def _date_list(self, start_date, end_date):
        res = []
        cur = fields.Date.from_string(start_date) if isinstance(start_date, str) else start_date
        end = fields.Date.from_string(end_date) if isinstance(end_date, str) else end_date
        while cur <= end:
            res.append(cur)
            cur = cur + timedelta(days=1)
        return res

    def _get_weekend_days(self):
        Param = self.env['ir.config_parameter'].sudo()
        weekend_days = []
        if Param.get_param('hr_payroll.weekend_mon') == 'True': weekend_days.append(0)
        if Param.get_param('hr_payroll.weekend_tue') == 'True': weekend_days.append(1)
        if Param.get_param('hr_payroll.weekend_wed') == 'True': weekend_days.append(2)
        if Param.get_param('hr_payroll.weekend_thu') == 'True': weekend_days.append(3)
        if Param.get_param('hr_payroll.weekend_fri') == 'True': weekend_days.append(4)
        if Param.get_param('hr_payroll.weekend_sat') == 'True': weekend_days.append(5)
        if Param.get_param('hr_payroll.weekend_sun') == 'True': weekend_days.append(6)
        return weekend_days

    def _get_emp_tzname(self, emp):
        contract = emp.contract_id or (emp.contract_ids[:1] if emp.contract_ids else False)
        cal = contract.resource_calendar_id if contract else False
        return (cal.tz if cal and cal.tz else False) or (self.env.user.tz or "UTC")

    def _ctx_ts(self, tzname, dt_utc):
        return fields.Datetime.context_timestamp(self.with_context(tz=tzname), dt_utc)

    def _last_attendance(self, day_att):
        return day_att.sorted(key=lambda a: ((a.check_out or a.check_in), a.id))[-1] if day_att else False

    # ---------------- attendance fetch/group ----------------
    def _search_attendances(self, emp, start_date, end_date):
        Attendance = self.env["hr.attendance"].sudo()
        start_dt = datetime.combine(start_date, time.min)
        end_dt = datetime.combine(end_date, time.max)
        return Attendance.search([
            ("employee_id", "=", emp.id),
            ("check_in", "<=", fields.Datetime.to_string(end_dt)),
            "|",
                ("check_out", "=", False),
                ("check_out", ">=", fields.Datetime.to_string(start_dt)),
        ], order="check_in asc")

    def _group_by_local_day(self, atts, tzname, start_date, end_date):
        Attendance = self.env["hr.attendance"].sudo()
        by_day = {}
        for a in atts:
            if not a.check_in:
                continue
            d = self._ctx_ts(tzname, a.check_in).date()
            if start_date <= d <= end_date:
                by_day.setdefault(d, Attendance.browse())
                by_day[d] |= a
        return by_day

    def _get_public_holidays_for_emp(self, emp, start_date, end_date, tzname):
        """Calendar global leaves (resource_id=False) for employee's calendar only."""
        contract = emp.contract_id or (emp.contract_ids[:1] if emp.contract_ids else False)
        cal = contract.resource_calendar_id if contract else False
        if not cal:
            return set()

        CalendarLeave = self.env["resource.calendar.leaves"].sudo()
        leaves = CalendarLeave.search([
            ("calendar_id", "=", cal.id),
            ("resource_id", "=", False),
            ("date_from", "<=", fields.Datetime.to_string(datetime.combine(end_date, time.max))),
            ("date_to", ">=", fields.Datetime.to_string(datetime.combine(start_date, time.min))),
        ])

        dates = set()
        for lv in leaves:
            if not (lv.date_from and lv.date_to):
                continue
            s_local = fields.Datetime.context_timestamp(self.with_context(tz=tzname), lv.date_from).date()
            e_local = fields.Datetime.context_timestamp(self.with_context(tz=tzname), lv.date_to).date()
            cur = s_local
            while cur <= e_local:
                if start_date <= cur <= end_date:
                    dates.add(cur)
                cur += timedelta(days=1)
        return dates

    # ---------------- core daily computation (READ ONLY from attendance) ----------------
    def _compute_employee_daily(self, emp, wizard):
        Attendance = self.env["hr.attendance"].sudo()
        start_date = wizard.date_start
        end_date = wizard.date_end

        tzname = self._get_emp_tzname(emp)
        weekend_days = self._get_weekend_days()
        public_holidays = self._get_public_holidays_for_emp(emp, start_date, end_date, tzname)

        # config: half/full day thresholds
        Param = self.env["ir.config_parameter"].sudo()
        half_day_hrs = float(Param.get_param("hr_payroll.half_day_hours", 4) or 4)
        full_day_hrs = float(Param.get_param("hr_payroll.full_day_hours", 8) or 8)

        atts = self._search_attendances(emp, start_date, end_date)
        by_day = self._group_by_local_day(atts, tzname, start_date, end_date)

        has_ot_amount = ("bambus_overtime_amount" in Attendance._fields)
        has_fine = ("bambus_fine_hours" in Attendance._fields and "bambus_fine_amount" in Attendance._fields)
        has_late = ("bambus_late_minutes" in Attendance._fields)
        has_sched = ("bambus_scheduled_hours" in Attendance._fields)
        has_short = ("bambus_shortfall_hours" in Attendance._fields)
        has_early = ("bambus_early_leave_minutes" in Attendance._fields)
        has_gap = ("bambus_gap_minutes" in Attendance._fields)

        dates = self._date_list(start_date, end_date)
        result = {}

        for d in dates:
            day_att = by_day.get(d, Attendance.browse())

            worked = sum(day_att.mapped("worked_hours")) if day_att else 0.0

            ot = 0.0
            ot_amount = 0.0
            if emp.employee_type != "worker" and day_att:
                ot = sum(max(0.0, (a.overtime_hours or 0.0)) for a in day_att)
                if has_ot_amount:
                    ot_amount = sum((a.bambus_overtime_amount or 0.0) for a in day_att)

            # last-attendance fields
            late_mins = 0
            early_mins = 0
            gap_mins = 0

            fine_hours = 0.0
            fine_amount = 0.0
            scheduled_hours = 0.0
            shortfall_hours = 0.0

            last = self._last_attendance(day_att) if day_att else False
            if last:
                if has_late:
                    late_mins = int(last.bambus_late_minutes or 0)
                if has_early:
                    early_mins = int(last.bambus_early_leave_minutes or 0)
                if has_gap:
                    gap_mins = int(last.bambus_gap_minutes or 0)

                if has_fine:
                    fine_hours = float(last.bambus_fine_hours or 0.0)
                    fine_amount = float(last.bambus_fine_amount or 0.0)
                if has_sched:
                    scheduled_hours = float(last.bambus_scheduled_hours or 0.0)
                if has_short:
                    shortfall_hours = float(last.bambus_shortfall_hours or 0.0)

            # For day-fraction we use worked excluding OT (still from attendance fields only)
            worked_excl_ot = max(0.0, worked - ot)

            if worked_excl_ot >= full_day_hrs:
                day_fraction = 1.0
                base_hours = full_day_hrs
            elif worked_excl_ot >= half_day_hrs:
                day_fraction = 0.5
                base_hours = worked_excl_ot
            else:
                day_fraction = 0.0
                base_hours = 0.0

            is_weekend = d.weekday() in weekend_days
            is_holiday = d in public_holidays

            # Absent flag: schedule exists AND not weekend/holiday
            shifts = wizard._get_shift_rules_for_employee_on_date(emp, d) if hasattr(wizard, "_get_shift_rules_for_employee_on_date") else []
            is_absent = (not day_att) and bool(shifts) and (not is_weekend) and (not is_holiday)

            # Sanity: Fine should match split (allow 1 minute rounding)
            fine_mins = int(round((fine_hours or 0.0) * 60.0))
            split_mins = int(late_mins or 0) + int(early_mins or 0) + int(gap_mins or 0)
            if abs(fine_mins - split_mins) > 1 and emp.employee_type != "worker":
                _logger.warning(
                    "Fine split mismatch (%s %s): fine=%s mins, split=%s mins (late=%s early=%s gap=%s)",
                    emp.name, d, fine_mins, split_mins, late_mins, early_mins, gap_mins
                )

            result[d] = {
                "attendances": day_att,
                "worked": worked,
                "worked_excl_ot": worked_excl_ot,
                "scheduled_hours": scheduled_hours,
                "shortfall_hours": shortfall_hours,  # should equal Fine if your OT/Fine code aligned it
                "ot": ot,
                "ot_amount": ot_amount,

                "late_minutes": late_mins,
                "early_leave_minutes": early_mins,
                "gap_minutes": gap_mins,

                "fine_hours": fine_hours,
                "fine_amount": fine_amount,

                "day_fraction": day_fraction,
                "base_hours": base_hours,
                "is_weekend": is_weekend,
                "is_holiday": is_holiday,
                "is_absent": is_absent,
            }

        return result

    def _totals_for_emp(self, emp, wizard):
        daily = self._compute_employee_daily(emp, wizard)
        dates = sorted(daily.keys())

        Param = self.env["ir.config_parameter"].sudo()
        grace_minutes = int(Param.get_param("custom_hr_payroll.late_login_grace_minutes", 0) or 0)

        # calendar day counts
        regular_days = sum(1 for d in dates if (not daily[d]["is_weekend"] and not daily[d]["is_holiday"]))
        weekend_days = sum(1 for d in dates if daily[d]["is_weekend"])
        holiday_days = sum(1 for d in dates if daily[d]["is_holiday"])

        # worked day fractions
        regular_worked = sum(daily[d]["day_fraction"] for d in dates if (not daily[d]["is_weekend"] and not daily[d]["is_holiday"]))
        weekend_worked = sum(daily[d]["day_fraction"] for d in dates if daily[d]["is_weekend"])
        holiday_worked = sum(daily[d]["day_fraction"] for d in dates if daily[d]["is_holiday"])

        # totals from attendance fields
        total_worked = sum(daily[d]["worked"] for d in dates)
        total_scheduled = sum(daily[d]["scheduled_hours"] for d in dates)
        total_shortfall = sum(daily[d]["shortfall_hours"] for d in dates)

        total_ot = sum(daily[d]["ot"] for d in dates)
        total_ot_amount = sum(daily[d]["ot_amount"] for d in dates)

        total_fine_hours = sum(daily[d]["fine_hours"] for d in dates)
        total_fine_amount = sum(daily[d]["fine_amount"] for d in dates)

        total_late_mins = sum(int(daily[d]["late_minutes"] or 0) for d in dates)
        total_early_mins = sum(int(daily[d]["early_leave_minutes"] or 0) for d in dates)
        total_gap_mins = sum(int(daily[d]["gap_minutes"] or 0) for d in dates)

        # ✅ Grace applies ONCE PER MONTH (overall), not per day
        total_late_after_grace_mins = max(0, int(total_late_mins or 0) - int(grace_minutes or 0))


        return {
            "daily": daily,
            "regular_days": float(regular_days),
            "weekend_days": float(weekend_days),
            "holiday_days": float(holiday_days),
            "regular_worked_days": float(regular_worked),
            "weekend_worked_days": float(weekend_worked),
            "holiday_worked_days": float(holiday_worked),
            "absent_regular_days": float(max(0.0, regular_days - regular_worked)),

            "total_worked_hours": float(total_worked),
            "total_scheduled_hours": float(total_scheduled),
            "total_shortfall_hours": float(total_shortfall),  # display as Shortfall vs Schedule

            "total_overtime_hours": float(total_ot),
            "total_overtime_amount": float(total_ot_amount),

            "total_fine_hours": float(total_fine_hours),
            "total_fine_amount": float(total_fine_amount),

            "total_late_minutes": int(total_late_mins),
            "total_early_leave_minutes": int(total_early_mins),
            "total_gap_minutes": int(total_gap_mins),

            "total_late_after_grace_minutes": int(total_late_after_grace_mins),
            "total_fine_after_grace_minutes": int(total_late_after_grace_mins + total_early_mins + total_gap_mins),
            "grace_minutes": int(grace_minutes),
        }

    # ---------------- top header builder ----------------
    def _write_report_header(self, workbook, sheet, wizard, employees):
        hdr_bold = workbook.add_format({'bold': True, 'font_size': 11})
        hdr_val = workbook.add_format({'font_size': 10})
        gen_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        company = ''
        try:
            company = employees[0].company_id.name if employees and employees[0].company_id else (self.env.company.name or '')
        except Exception:
            company = self.env.company.name or ''
        report_name = wizard._get_report_name() if hasattr(wizard, '_get_report_name') else ''
        period_text = "From: %s   To: %s" % (wizard.date_start or '', wizard.date_end or '')

        # widen header (we have more columns)
        sheet.merge_range(0, 0, 0, 14, f"Company: {company}", hdr_bold)
        sheet.write(1, 0, "Report:", hdr_bold)
        sheet.write(1, 1, report_name, hdr_val)
        sheet.write(2, 0, "Period:", hdr_bold)
        sheet.write(2, 1, period_text, hdr_val)
        sheet.write(1, 13, "Generated On:", hdr_bold)
        sheet.write(1, 14, gen_dt, hdr_val)
        return 4

    # ---------------- main entry (dispatcher) ----------------
    def generate_xlsx_report(self, workbook, data, wizard):
        employees = wizard._get_employees()
        rpt = wizard.report_type or 'attendance'
        if rpt == 'attendance':
            return self._report_attendance_summary(workbook, data, wizard, employees)
        if rpt == 'overtime':
            return self._report_overtime_summary(workbook, data, wizard, employees)
        if rpt == 'late':
            return self._report_fine_breakdown_summary(workbook, data, wizard, employees)
        if rpt == 'monthly':
            return self._report_monthly_summary(workbook, data, wizard, employees)
        return self._report_attendance_summary(workbook, data, wizard, employees)

    # -------------------------------------------------------------------------
    # Attendance report
    # -------------------------------------------------------------------------
    def _report_attendance_summary(self, workbook, data, wizard, employees):
        header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})
        alert_fmt = workbook.add_format({'font_color': 'red'})
        weekend_fmt = workbook.add_format({'bg_color': '#FFE5CC'})
        holiday_fmt = workbook.add_format({'bg_color': '#FFF5CC'})
        absent_fmt = workbook.add_format({'bg_color': '#FFECEC'})

        sheet = workbook.add_worksheet("Attendance Summary"[:31])
        header_row = self._write_report_header(workbook, sheet, wizard, employees)

        headers = [
            "S.No", "Staff",
            "Worked Hours", "Scheduled Hours", "Shortfall vs Schedule",
            "OT Hours", "OT Amount",
            "Fine Hours",
            "Late", "Early Leave", "Gap",
            "Fine After Grace",
            "Fine Amount",
        ]
        for c, h in enumerate(headers):
            sheet.write(header_row, c, h, header_format)
        sheet.freeze_panes(header_row + 1, 0)

        row = header_row + 1
        idx = 1
        for emp in employees:
            tot = self._totals_for_emp(emp, wizard)
            fmt = alert_fmt if (tot["total_fine_amount"] > 0 or tot["total_fine_hours"] > 0 or tot["total_late_minutes"] > 0) else None

            sheet.write(row, 0, idx, fmt)
            sheet.write(row, 1, emp.name, fmt)
            sheet.write(row, 2, self.float_to_time(tot["total_worked_hours"]), fmt)
            sheet.write(row, 3, self.float_to_time(tot["total_scheduled_hours"]), fmt)
            sheet.write(row, 4, self.float_to_time(tot["total_shortfall_hours"]), fmt)

            # OT/Fine hidden for worker (as your original behavior)
            sheet.write(row, 5, self.float_to_time(tot["total_overtime_hours"]) if emp.employee_type != "worker" else "00:00", fmt)
            sheet.write(row, 6, tot["total_overtime_amount"] if emp.employee_type != "worker" else 0.0, fmt)

            sheet.write(row, 7, self.float_to_time(tot["total_fine_hours"]) if emp.employee_type != "worker" else "00:00", fmt)

            sheet.write(row, 8, self.minutes_to_time(tot["total_late_minutes"]) if emp.employee_type != "worker" else "00:00", fmt)
            sheet.write(row, 9, self.minutes_to_time(tot["total_early_leave_minutes"]) if emp.employee_type != "worker" else "00:00", fmt)
            sheet.write(row, 10, self.minutes_to_time(tot["total_gap_minutes"]) if emp.employee_type != "worker" else "00:00", fmt)

            sheet.write(row, 11, self.minutes_to_time(tot["total_fine_after_grace_minutes"]) if emp.employee_type != "worker" else "00:00", fmt)

            sheet.write(row, 12, tot["total_fine_amount"] if emp.employee_type != "worker" else 0.0, fmt)

            row += 1
            idx += 1

        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 26)
        sheet.set_column(2, 4, 18)
        sheet.set_column(5, 5, 14)
        sheet.set_column(6, 6, 14)
        sheet.set_column(7, 7, 14)
        sheet.set_column(8, 11, 14)
        sheet.set_column(12, 12, 16)

        # Per-employee detailed sheets
        for emp in employees:
            sheet_name = f"{emp.name[:20]}"
            sheet_e = workbook.add_worksheet(sheet_name[:31])
            header_row = self._write_report_header(workbook, sheet_e, wizard, employees)

            headers = [
                "Date", "Day",
                "Worked Hours", "Scheduled Hours", "Shortfall vs Schedule",
                "OT Hours", "OT Amount",
                "Late", "Early Leave", "Gap",
                "Fine Hours", "Fine After Grace",
                "Fine Amount",
                "Day Type", "Note"
            ]
            for c, h in enumerate(headers):
                sheet_e.write(header_row, c, h, header_format)
            sheet_e.freeze_panes(header_row + 1, 0)

            tot = self._totals_for_emp(emp, wizard)
            daily = tot["daily"]
            grace_minutes = int(tot["grace_minutes"] or 0)

            r = header_row + 1

            for d in sorted(daily.keys()):
                info = daily[d]
                note = ""
                row_fmt = None
                if info["is_holiday"]:
                    note = "Public Holiday"
                    row_fmt = holiday_fmt
                elif info["is_weekend"]:
                    note = "Weekend"
                    row_fmt = weekend_fmt
                elif info["is_absent"]:
                    note = "Absent"
                    row_fmt = absent_fmt

                sheet_e.write(r, 0, d.strftime('%d-%b-%Y'), row_fmt)
                sheet_e.write(r, 1, d.strftime('%A'), row_fmt)

                sheet_e.write(r, 2, self.float_to_time(info["worked"]), row_fmt)
                sheet_e.write(r, 3, self.float_to_time(info["scheduled_hours"]), row_fmt)
                sheet_e.write(r, 4, self.float_to_time(info["shortfall_hours"]), row_fmt)

                if emp.employee_type == "worker":
                    sheet_e.write(r, 5, "00:00", row_fmt)
                    sheet_e.write(r, 6, 0.0, row_fmt)
                    sheet_e.write(r, 7, "00:00", row_fmt)
                    sheet_e.write(r, 8, "00:00", row_fmt)
                    sheet_e.write(r, 9, "00:00", row_fmt)
                    sheet_e.write(r, 10, "00:00", row_fmt)
                    sheet_e.write(r, 11, "00:00", row_fmt)
                    sheet_e.write(r, 12, 0.0, row_fmt)
                else:
                    sheet_e.write(r, 5, self.float_to_time(info["ot"]), row_fmt)
                    sheet_e.write(r, 6, info["ot_amount"], row_fmt)

                    sheet_e.write(r, 7, self.minutes_to_time(info["late_minutes"]), row_fmt)
                    sheet_e.write(r, 8, self.minutes_to_time(info["early_leave_minutes"]), row_fmt)
                    sheet_e.write(r, 9, self.minutes_to_time(info["gap_minutes"]), row_fmt)

                    sheet_e.write(r, 10, self.float_to_time(info["fine_hours"]), row_fmt)

                    late_after = max(0, int(info["late_minutes"] or 0) - grace_minutes)
                    sheet_e.write(r, 11, "-", row_fmt)


                    sheet_e.write(r, 12, info["fine_amount"], row_fmt)

                day_type = "Public Holiday" if info["is_holiday"] else ("Weekend" if info["is_weekend"] else ("Absent" if info["is_absent"] else "Working Day"))
                sheet_e.write(r, 13, day_type, row_fmt)
                sheet_e.write(r, 14, note, row_fmt)
                r += 1

            sheet_e.set_column(0, 0, 14)
            sheet_e.set_column(1, 1, 12)
            sheet_e.set_column(2, 4, 18)
            sheet_e.set_column(5, 5, 14)
            sheet_e.set_column(6, 6, 14)
            sheet_e.set_column(7, 12, 14)
            sheet_e.set_column(13, 14, 18)

    # -------------------------------------------------------------------------
    # Overtime report
    # -------------------------------------------------------------------------
    def _report_overtime_summary(self, workbook, data, wizard, employees):
        header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})

        sheet = workbook.add_worksheet("Overtime Report"[:31])
        header_row = self._write_report_header(workbook, sheet, wizard, employees)

        headers = ["S.No", "Staff", "OT Hours", "OT Amount", "Note"]
        for c, h in enumerate(headers):
            sheet.write(header_row, c, h, header_format)
        sheet.freeze_panes(header_row + 1, 0)

        row = header_row + 1
        idx = 1

        for emp in employees:
            if emp.employee_type == "worker":
                continue

            tot = self._totals_for_emp(emp, wizard)
            if tot["total_overtime_hours"] <= 0:
                continue

            note = ""
            daily = tot["daily"]
            if any(info["is_weekend"] and info["ot"] > 0 for info in daily.values()):
                note = "Weekend"

            sheet.write(row, 0, idx)
            sheet.write(row, 1, emp.name)
            sheet.write(row, 2, self.float_to_time(tot["total_overtime_hours"]))
            sheet.write(row, 3, tot["total_overtime_amount"])
            sheet.write(row, 4, note)
            row += 1
            idx += 1

        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 28)
        sheet.set_column(2, 2, 14)
        sheet.set_column(3, 3, 16)
        sheet.set_column(4, 4, 14)

    # -------------------------------------------------------------------------
    # Fine Breakdown report (report_type == 'late' kept, but content is clean)
    # -------------------------------------------------------------------------
    def _report_fine_breakdown_summary(self, workbook, data, wizard, employees):
        header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})
        alert_fmt = workbook.add_format({'font_color': 'red'})

        sheet = workbook.add_worksheet("Fine Breakdown"[:31])
        header_row = self._write_report_header(workbook, sheet, wizard, employees)

        headers = [
            "S.No", "Staff",
            "Fine Hours", "Fine After Grace", "Penalty Amount",
            "Late", "Early Leave", "Gap",
            "Scheduled Hours", "Shortfall vs Schedule",
        ]
        for c, h in enumerate(headers):
            sheet.write(header_row, c, h, header_format)
        sheet.freeze_panes(header_row + 1, 0)

        row = header_row + 1
        idx = 1

        for emp in employees:
            if emp.employee_type == "worker":
                continue

            tot = self._totals_for_emp(emp, wizard)
            if tot["total_fine_hours"] <= 0 and tot["total_late_minutes"] <= 0 and tot["total_fine_amount"] <= 0:
                continue

            row_fmt = alert_fmt if (tot["total_fine_hours"] > 0 or tot["total_fine_amount"] > 0) else None

            sheet.write(row, 0, idx, row_fmt)
            sheet.write(row, 1, emp.name, row_fmt)

            sheet.write(row, 2, self.float_to_time(tot["total_fine_hours"]), row_fmt)
            sheet.write(row, 3, self.minutes_to_time(tot["total_late_after_grace_minutes"]), row_fmt)
            sheet.write(row, 4, tot["total_fine_amount"], row_fmt)

            sheet.write(row, 5, self.minutes_to_time(tot["total_late_minutes"]), row_fmt)
            sheet.write(row, 6, self.minutes_to_time(tot["total_early_leave_minutes"]), row_fmt)
            sheet.write(row, 7, self.minutes_to_time(tot["total_gap_minutes"]), row_fmt)

            sheet.write(row, 8, self.float_to_time(tot["total_scheduled_hours"]), row_fmt)
            sheet.write(row, 9, self.float_to_time(tot["total_shortfall_hours"]), row_fmt)

            row += 1
            idx += 1

        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 28)
        sheet.set_column(2, 2, 14)
        sheet.set_column(3, 3, 16)
        sheet.set_column(4, 4, 16)
        sheet.set_column(5, 7, 14)
        sheet.set_column(8, 9, 18)

    # -------------------------------------------------------------------------
    # Monthly summary
    # -------------------------------------------------------------------------
    def _report_monthly_summary(self, workbook, data, wizard, employees):
        header_format = workbook.add_format({'bold': True, 'bg_color': '#F2F2F2', 'border': 1})
        alert_fmt = workbook.add_format({'font_color': 'red'})
        absent_fmt = workbook.add_format({'bg_color': '#FFECEC'})
        weekend_fmt = workbook.add_format({'bg_color': '#FFE5CC'})
        holiday_fmt = workbook.add_format({'bg_color': '#FFF5CC'})

        sheet = workbook.add_worksheet("Monthly Summary"[:31])
        header_row = self._write_report_header(workbook, sheet, wizard, employees)

        headers = [
            "S.No", "Staff",
            "Regular Days", "Weekend Days", "Public Holidays",
            "Regular Worked", "Weekend Worked", "Holiday Worked", "Absent (Regular)",
            "Scheduled Hours", "Shortfall vs Schedule",
            "Total Worked Hours",
            "OT Hours", "OT Amount",
            "Fine Hours",
            "Late", "Early Leave", "Gap",
            "Fine After Grace",
            "Fine Amount"
        ]
        for c, h in enumerate(headers):
            sheet.write(header_row, c, h, header_format)
        sheet.freeze_panes(header_row + 1, 0)

        row = header_row + 1
        idx = 1

        for emp in employees:
            tot = self._totals_for_emp(emp, wizard)
            row_fmt = alert_fmt if (tot["total_fine_amount"] > 0 or tot["total_fine_hours"] > 0 or tot["total_shortfall_hours"] > 0) else None

            sheet.write(row, 0, idx, row_fmt)
            sheet.write(row, 1, emp.name, row_fmt)
            sheet.write(row, 2, tot["regular_days"], row_fmt)
            sheet.write(row, 3, tot["weekend_days"], row_fmt)
            sheet.write(row, 4, tot["holiday_days"], row_fmt)

            sheet.write(row, 5, tot["regular_worked_days"], row_fmt)
            sheet.write(row, 6, tot["weekend_worked_days"], row_fmt)
            sheet.write(row, 7, tot["holiday_worked_days"], row_fmt)
            sheet.write(row, 8, tot["absent_regular_days"], row_fmt)

            sheet.write(row, 9, self.float_to_time(tot["total_scheduled_hours"]), row_fmt)
            sheet.write(row, 10, self.float_to_time(tot["total_shortfall_hours"]), row_fmt)

            sheet.write(row, 11, self.float_to_time(tot["total_worked_hours"]), row_fmt)

            sheet.write(row, 12, self.float_to_time(tot["total_overtime_hours"]) if emp.employee_type != "worker" else "00:00", row_fmt)
            sheet.write(row, 13, tot["total_overtime_amount"] if emp.employee_type != "worker" else 0.0, row_fmt)

            sheet.write(row, 14, self.float_to_time(tot["total_fine_hours"]) if emp.employee_type != "worker" else "00:00", row_fmt)

            sheet.write(row, 15, self.minutes_to_time(tot["total_late_minutes"]) if emp.employee_type != "worker" else "00:00", row_fmt)
            sheet.write(row, 16, self.minutes_to_time(tot["total_early_leave_minutes"]) if emp.employee_type != "worker" else "00:00", row_fmt)
            sheet.write(row, 17, self.minutes_to_time(tot["total_gap_minutes"]) if emp.employee_type != "worker" else "00:00", row_fmt)

            sheet.write(row, 18, self.minutes_to_time(tot["total_fine_after_grace_minutes"]) if emp.employee_type != "worker" else "00:00", row_fmt)

            sheet.write(row, 19, tot["total_fine_amount"] if emp.employee_type != "worker" else 0.0, row_fmt)

            row += 1
            idx += 1

        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 26)
        sheet.set_column(2, 8, 16)
        sheet.set_column(9, 11, 18)
        sheet.set_column(12, 12, 14)
        sheet.set_column(13, 13, 14)
        sheet.set_column(14, 14, 14)
        sheet.set_column(15, 18, 14)
        sheet.set_column(19, 19, 16)

        # Per-employee day-wise sheets (same as your original)
        for emp in employees:
            sheet_name = f"{emp.name[:20]} {fields.Date.from_string(wizard.date_start).strftime('%b')}"
            sheet_e = workbook.add_worksheet(sheet_name[:31])
            hdr = self._write_report_header(workbook, sheet_e, wizard, employees)

            cols = [
                "Date", "Day",
                "Worked Hours", "Scheduled Hours", "Shortfall vs Schedule",
                "OT Hours", "OT Amount",
                "Late", "Early Leave", "Gap",
                "Fine Hours", "Fine After Grace",
                "Fine Amount",
                "Day Type", "Note"
            ]
            for c, h in enumerate(cols):
                sheet_e.write(hdr, c, h, header_format)
            sheet_e.freeze_panes(hdr + 1, 0)

            tot = self._totals_for_emp(emp, wizard)
            daily = tot["daily"]
            grace_minutes = int(tot["grace_minutes"] or 0)

            r = hdr + 1
            for d in sorted(daily.keys()):
                info = daily[d]
                note = ""
                row_fmt = None
                if info["is_holiday"]:
                    note = "Public Holiday"
                    row_fmt = holiday_fmt
                elif info["is_weekend"]:
                    note = "Weekend"
                    row_fmt = weekend_fmt
                elif info["is_absent"]:
                    note = "Absent"
                    row_fmt = absent_fmt

                sheet_e.write(r, 0, d.strftime('%d-%b-%Y'), row_fmt)
                sheet_e.write(r, 1, d.strftime('%A'), row_fmt)

                sheet_e.write(r, 2, self.float_to_time(info["worked"]), row_fmt)
                sheet_e.write(r, 3, self.float_to_time(info["scheduled_hours"]), row_fmt)
                sheet_e.write(r, 4, self.float_to_time(info["shortfall_hours"]), row_fmt)

                if emp.employee_type == "worker":
                    sheet_e.write(r, 5, "00:00", row_fmt)
                    sheet_e.write(r, 6, 0.0, row_fmt)
                    sheet_e.write(r, 7, "00:00", row_fmt)
                    sheet_e.write(r, 8, "00:00", row_fmt)
                    sheet_e.write(r, 9, "00:00", row_fmt)
                    sheet_e.write(r, 10, "00:00", row_fmt)
                    sheet_e.write(r, 11, "00:00", row_fmt)
                    sheet_e.write(r, 12, 0.0, row_fmt)
                else:
                    sheet_e.write(r, 5, self.float_to_time(info["ot"]), row_fmt)
                    sheet_e.write(r, 6, info["ot_amount"], row_fmt)

                    sheet_e.write(r, 7, self.minutes_to_time(info["late_minutes"]), row_fmt)
                    sheet_e.write(r, 8, self.minutes_to_time(info["early_leave_minutes"]), row_fmt)
                    sheet_e.write(r, 9, self.minutes_to_time(info["gap_minutes"]), row_fmt)

                    sheet_e.write(r, 10, self.float_to_time(info["fine_hours"]), row_fmt)

                    late_after = max(0, int(info["late_minutes"] or 0) - grace_minutes)
                    sheet_e.write(r, 11, "-", row_fmt)

                    sheet_e.write(r, 12, info["fine_amount"], row_fmt)

                day_type = "Public Holiday" if info["is_holiday"] else ("Weekend" if info["is_weekend"] else ("Absent" if info["is_absent"] else "Working Day"))
                sheet_e.write(r, 13, day_type, row_fmt)
                sheet_e.write(r, 14, note, row_fmt)
                r += 1

            sheet_e.set_column(0, 0, 14)
            sheet_e.set_column(1, 1, 12)
            sheet_e.set_column(2, 4, 18)
            sheet_e.set_column(5, 5, 14)
            sheet_e.set_column(6, 6, 14)
            sheet_e.set_column(7, 12, 14)
            sheet_e.set_column(13, 14, 18)
