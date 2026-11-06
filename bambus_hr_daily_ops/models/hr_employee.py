# -*- coding: utf-8 -*-
from calendar import monthrange
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    payslip_currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Payslip Currency",
        readonly=True,
    )
    latest_payslip_amount = fields.Monetary(
        compute="_compute_salary_overview",
        currency_field="payslip_currency_id",
        string="Latest Net Pay",
    )
    year_to_date_pay = fields.Monetary(
        compute="_compute_salary_overview",
        currency_field="payslip_currency_id",
        string="Year-to-date Pay",
    )

    def _compute_salary_overview(self):
        """Show payroll totals without changing the source payslip records."""
        year_start = fields.Date.context_today(self).replace(month=1, day=1)
        for employee in self:
            completed_slips = employee.slip_ids.filtered(
                lambda slip: slip.state == "done"
            ).sorted(
                key=lambda slip: (slip.date_to or slip.date_from, slip.id),
                reverse=True,
            )
            employee.latest_payslip_amount = (
                completed_slips[:1].net_pay if completed_slips else 0.0
            )
            employee.year_to_date_pay = sum(
                completed_slips.filtered(
                    lambda slip: slip.date_to and slip.date_to >= year_start
                ).mapped("net_pay")
            )

    def action_open_salary_overview(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "hr_payroll_community.action_hr_payslip"
        )
        action.update(
            {
                "name": _("Salary Overview - %s", self.name),
                "domain": [("employee_id", "=", self.id)],
                "context": {
                    "default_employee_id": self.id,
                    "search_default_employee_id": self.id,
                },
            }
        )
        return action

    def action_open_salary_revision_history(self):
        self.ensure_one()
        self.check_access('read')
        self.env['hr.salary.revision'].check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Salary Revision History - %s', self.name),
            'res_model': 'hr.salary.revision',
            'views': [(self.env.ref('bambus_hr_daily_ops.salary_revision_history_list').id, 'list'),
                      (self.env.ref('bambus_hr_daily_ops.salary_revision_history_form').id, 'form')],
            'domain': [('employee_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
            'help': _('No salary revisions have been recorded for this employee.'),
        }

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
        timezone = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")
        utc = pytz.UTC
        range_start = timezone.localize(datetime.combine(month_start, time.min)).astimezone(utc).replace(tzinfo=None)
        range_end = timezone.localize(datetime.combine(month_end + timedelta(days=1), time.min)).astimezone(utc).replace(tzinfo=None)

        attendances = self.env["hr.attendance"].search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", range_start),
            ("check_in", "<", range_end),
        ], order="check_in asc")

        # Refresh the selected employee once, rather than loading the whole
        # company dashboard for every date. Adjacent dates cover timezone edges.
        if attendances:
            self.env['hr.attendance.overtime'].sudo().bambus_recompute_range(
                employee.ids, month_start - timedelta(days=1), month_end + timedelta(days=1))

        def empty_row(day):
            return {'date': fields.Date.to_string(day), 'status': 'not_marked',
                    'status_label': _('Not Marked'), 'check_in': '', 'check_out': '',
                    'check_out_day_offset': 0, 'check_out_date': '', 'has_open_attendance': False,
                    'worked_hours': 0.0, 'overtime_hours': 0.0, 'fine_hours': 0.0,
                    'logs': [], 'leave_id': False}

        def optional_value(attendance, field_name, default=""):
            """Read fields supplied by optional attendance integrations safely."""
            if field_name not in attendance._fields:
                return default
            return getattr(attendance, field_name, default) or default

        def attendance_mode(attendance, field_name):
            field = attendance._fields.get(field_name)
            if not field:
                return _("Attendance")
            value = getattr(attendance, field_name, False)
            return field.convert_to_export(value, attendance) or _("Attendance")

        def attendance_image_url(attendance, field_name):
            if not optional_value(attendance.with_context(bin_size=True), field_name):
                return ""
            return f"/web/image/hr.attendance/{attendance.id}/{field_name}"

        rows = {}
        punches_by_day = {}
        for attendance in attendances:
            local_in = utc.localize(attendance.check_in).astimezone(timezone)
            local_out = utc.localize(attendance.check_out).astimezone(timezone) if attendance.check_out else False
            day = local_in.date()
            row = rows.setdefault(day, empty_row(day))
            punches_by_day.setdefault(day, []).append(attendance)
            row.update(status='present', status_label=_('Present'))
            if not row['check_in']:
                row['check_in'] = local_in.strftime('%I:%M %p').lstrip('0')
            row['has_open_attendance'] |= not bool(attendance.check_out)
            if attendance.check_in:
                row["logs"].append({
                    "id": f"{attendance.id}-in",
                    "type": "check_in",
                    "label": _("Punched In"),
                    "time": local_in.strftime("%I:%M %p").lstrip("0"),
                    "day_offset": 0,
                    "mode": attendance_mode(attendance, "in_mode"),
                    "address": optional_value(attendance, "checkin_reverse_address"),
                    "image_url": attendance_image_url(attendance, "recognized_face_checkin"),
                })
            if local_out:
                # Select the latest actual checkout, even with split sessions.
                completed = [a.check_out for a in punches_by_day[day] if a.check_out]
                latest_out = utc.localize(max(completed)).astimezone(timezone)
                row['check_out'] = latest_out.strftime('%I:%M %p').lstrip('0')
                row['check_out_day_offset'] = (latest_out.date() - day).days
                row['check_out_date'] = fields.Date.to_string(latest_out.date())
                row["logs"].append({
                    "id": f"{attendance.id}-out",
                    "type": "check_out",
                    "label": _("Punched Out"),
                    "time": local_out.strftime("%I:%M %p").lstrip("0"),
                    "day_offset": (local_out.date() - day).days,
                    "mode": attendance_mode(attendance, "out_mode"),
                    "address": optional_value(attendance, "checkout_reverse_address"),
                    "image_url": attendance_image_url(attendance, "recognized_face_checkout"),
                })
            row["worked_hours"] += attendance.worked_hours or 0.0

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
                row = rows.setdefault(day, empty_row(day))
                row['leave_id'] = leave.id
                if leave.state == 'validate':
                    is_half_day = bool(getattr(leave, 'request_unit_half', False))
                    row['status'] = 'halfday' if is_half_day else 'leave'
                    row['status_label'] = _('Half Day') if is_half_day else _('Leave')
                day += timedelta(days=1)

        # Explicit HR decisions overlay status only; actual punches and current
        # leave remain authoritative even when a review was opened previously.
        sheet_lines = self.env["bambus.attendance.day.review"].search([
            ("employee_id", "=", employee.id),
            ("company_id", "=", employee.company_id.id),
            ("date", ">=", month_start),
            ("date", "<=", month_end),
        ], order="date asc")
        status_labels = {
            "present": _("Present"), "absent": _("Absent"),
            "halfday": _("Half Day"), "leave": _("Leave"),
        }
        reviews_by_day = {line.date: line for line in sheet_lines}
        for line in sheet_lines:
            if not line.attendance_status_manual:
                continue
            row = rows.setdefault(line.date, empty_row(line.date))
            row['status'] = line.status
            row['status_label'] = status_labels[line.status]

        service = self.env['bambus.attendance.dashboard']
        # Match the daily dashboard's derived Monthly paid-day statuses without
        # creating punches, leave requests or review records.
        day = month_start
        while day <= month_end:
            contract = employee._get_attendance_contract(day)
            info = service._paid_day_info(employee, day, contract) if contract and contract.company_id == employee.company_id else {}
            if info.get('kind') and (day in rows or info['eligible'] or info['withheld']):
                row = rows.setdefault(day, empty_row(day))
                row.update(paid_day_kind=info['kind'], paid_day_eligible=info['eligible'],
                           paid_day_withheld=info['withheld'], paid_day_reason=info['reason'])
            if info.get('kind') and (info['eligible'] or info['withheld']):
                row = rows.setdefault(day, empty_row(day))
                if row['status'] == 'not_marked':
                    row['status'] = ('unpaid_' if info['withheld'] else 'paid_') + info['kind']
                    row['status_label'] = {
                        'paid_public_holiday': _('Paid Public Holiday'), 'paid_weekly_off': _('Paid Weekly Off'),
                        'unpaid_public_holiday': _('Unpaid Public Holiday'), 'unpaid_weekly_off': _('Unpaid Weekly Off'),
                    }[row['status']]
            day += timedelta(days=1)
        for day, row in rows.items():
            row.update(service._employee_day_adjustments(
                employee, day, punches_by_day.get(day, []), reviews_by_day.get(day)))

        result_rows = [rows[day] for day in sorted(rows)]
        for row in result_rows:
            for key in ("worked_hours", "overtime_hours", "fine_hours"):
                row[key] = round(row[key], 2)
        return {
            "employee": {"id": employee.id, "name": employee.name, "barcode": employee.barcode or ""},
            "can_manage_attendance": bool(self.env.user.has_group('hr.group_hr_user') and employee.company_id == self.env.company),
            "month": month_start.strftime("%Y-%m"),
            "month_label": month_start.strftime("%B %Y"),
            "rows": result_rows,
            "metrics": {
                "days": len(result_rows),
                "present": sum(row["status"] == "present" for row in result_rows),
                "absent": sum(row["status"] == "absent" for row in result_rows),
                "halfday": sum(row["status"] == "halfday" for row in result_rows),
                "leave": sum(row["status"] == "leave" for row in result_rows),
                "not_marked": sum(row['status'] == 'not_marked' for row in result_rows),
                "paid_off": sum(row['status'].startswith('paid_') for row in result_rows),
                "unpaid_off": sum(row['status'].startswith('unpaid_') for row in result_rows),
                "punched_in": sum(bool(row["check_in"]) for row in result_rows),
                "punched_out": sum(bool(row["check_out"]) for row in result_rows),
            },
        }
