# -*- coding: utf-8 -*-
from calendar import monthrange
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def action_open_monthly_attendance(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "name": _("Attendance"),
            "tag": "bambus_employee_attendance",
            "params": {"employee_id": self.id},
            "context": {"active_id": self.id, "active_model": "hr.employee"},
        }

    @api.model
    def get_monthly_attendance(self, employee_id=None, month=None):
        employee = self.browse(employee_id).exists()
        if not employee:
            raise UserError(_("The employee no longer exists."))
        employee.check_access("read")

        today = fields.Date.context_today(self)
        try:
            selected_month = fields.Date.to_date(f"{month}-01") if month else today.replace(day=1)
        except (TypeError, ValueError):
            raise UserError(_("Select a valid month."))
        month_start = selected_month.replace(day=1)
        month_end = selected_month.replace(day=monthrange(selected_month.year, selected_month.month)[1])
        timezone = pytz.timezone(self.env.user.tz or "UTC")
        utc = pytz.UTC
        range_start = timezone.localize(datetime.combine(month_start, time.min)).astimezone(utc).replace(tzinfo=None)
        range_end = timezone.localize(datetime.combine(month_end + timedelta(days=1), time.min)).astimezone(utc).replace(tzinfo=None)

        attendances = self.env["hr.attendance"].search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", range_start),
            ("check_in", "<", range_end),
        ], order="check_in asc")
        rows = {}
        for attendance in attendances:
            local_in = utc.localize(attendance.check_in).astimezone(timezone)
            local_out = utc.localize(attendance.check_out).astimezone(timezone) if attendance.check_out else False
            day = local_in.date()
            row = rows.setdefault(day, {
                "date": fields.Date.to_string(day),
                "status": "present",
                "status_label": _("Present"),
                "check_in": local_in.strftime("%I:%M %p").lstrip("0"),
                "check_out": "",
                "worked_hours": 0.0,
                "overtime_hours": 0.0,
                "fine_hours": 0.0,
                "logs": [],
                "leave_id": False,
            })
            if attendance.recognized_face_checkin or attendance.check_in:
                row["logs"].append({
                    "id": f"{attendance.id}-in",
                    "type": "check_in",
                    "label": _("Punched In"),
                    "time": local_in.strftime("%I:%M %p").lstrip("0"),
                    "mode": attendance._fields["in_mode"].convert_to_export(attendance.in_mode, attendance) or _("Face"),
                    "address": attendance.checkin_reverse_address or "",
                    "image_url": f"/web/image/hr.attendance/{attendance.id}/recognized_face_checkin" if attendance.recognized_face_checkin else "",
                })
            if local_out:
                row["check_out"] = local_out.strftime("%I:%M %p").lstrip("0")
                row["logs"].append({
                    "id": f"{attendance.id}-out",
                    "type": "check_out",
                    "label": _("Punched Out"),
                    "time": local_out.strftime("%I:%M %p").lstrip("0"),
                    "mode": attendance._fields["out_mode"].convert_to_export(attendance.out_mode, attendance) or _("Face"),
                    "address": attendance.checkout_reverse_address or "",
                    "image_url": f"/web/image/hr.attendance/{attendance.id}/recognized_face_checkout" if attendance.recognized_face_checkout else "",
                })
            row["worked_hours"] += attendance.worked_hours or 0.0
            row["overtime_hours"] += attendance.overtime_hours or 0.0
            if "fine_hours" in attendance._fields:
                row["fine_hours"] += attendance.fine_hours or 0.0

        leaves = self.env["hr.leave"].search([
            ("employee_id", "=", employee.id),
            ("state", "in", ["confirm", "validate1", "validate"]),
            ("date_from", "<", range_end),
            ("date_to", ">=", range_start),
        ])
        for leave in leaves:
            leave_start = max(fields.Datetime.context_timestamp(self, leave.date_from).date(), month_start)
            leave_end = min(fields.Datetime.context_timestamp(self, leave.date_to).date(), month_end)
            day = leave_start
            while day <= leave_end:
                if day in rows:
                    rows[day]["leave_id"] = leave.id
                else:
                    is_half_day = bool(getattr(leave, "request_unit_half", False))
                    rows[day] = {
                        "date": fields.Date.to_string(day),
                        "status": "halfday" if is_half_day else "leave",
                        "status_label": _("Half Day") if is_half_day else _("Leave"),
                        "check_in": "", "check_out": "", "worked_hours": 0.0,
                        "overtime_hours": 0.0, "fine_hours": 0.0,
                        "logs": [],
                        "leave_id": leave.id,
                    }
                day += timedelta(days=1)

        # Daily sheets are the operational source for explicit absences and
        # manager-adjusted statuses. Overlay them so this screen agrees with
        # the Attendance History workflow.
        sheet_lines = self.env["bambus.hr.attendance.sheet.line"].search([
            ("employee_id", "=", employee.id),
            ("date", ">=", month_start),
            ("date", "<=", month_end),
        ], order="date asc")
        status_labels = {
            "present": _("Present"), "absent": _("Absent"),
            "halfday": _("Half Day"), "leave": _("Leave"),
        }
        for line in sheet_lines:
            local_in = fields.Datetime.context_timestamp(self, line.check_in) if line.check_in else False
            local_out = fields.Datetime.context_timestamp(self, line.check_out) if line.check_out else False
            rows[line.date] = {
                "date": fields.Date.to_string(line.date),
                "status": line.status,
                "status_label": status_labels.get(line.status, line.status or ""),
                "check_in": local_in.strftime("%I:%M %p").lstrip("0") if local_in else "",
                "check_out": local_out.strftime("%I:%M %p").lstrip("0") if local_out else "",
                "worked_hours": line.worked_hours or 0.0,
                "overtime_hours": line.overtime_hours or 0.0,
                "fine_hours": line.fine_hours or 0.0,
                "logs": rows.get(line.date, {}).get("logs", []),
                "leave_id": line.leave_id.id or rows.get(line.date, {}).get("leave_id", False),
            }

        result_rows = [rows[day] for day in sorted(rows)]
        for row in result_rows:
            for key in ("worked_hours", "overtime_hours", "fine_hours"):
                row[key] = round(row[key], 2)
        return {
            "employee": {"id": employee.id, "name": employee.name, "barcode": employee.barcode or ""},
            "month": month_start.strftime("%Y-%m"),
            "month_label": month_start.strftime("%B %Y"),
            "rows": result_rows,
            "metrics": {
                "days": len(result_rows),
                "present": sum(row["status"] == "present" for row in result_rows),
                "absent": sum(row["status"] == "absent" for row in result_rows),
                "halfday": sum(row["status"] == "halfday" for row in result_rows),
                "leave": sum(row["status"] == "leave" for row in result_rows),
                "punched_in": sum(bool(row["check_in"]) for row in result_rows),
                "punched_out": sum(bool(row["check_out"]) for row in result_rows),
            },
        }
