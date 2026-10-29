# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, time, timedelta
import pytz


class AttendanceDashboard(models.AbstractModel):
    _name = 'bambus.attendance.dashboard'
    _description = 'Daily Attendance Service'

    @api.model
    def _paid_day_info(self, employee, day, contract):
        info = {"kind": False, "eligible": False, "withheld": False, "reason": ""}
        if not contract or contract.wage_type != "monthly":
            return info
        tzname = contract.resource_calendar_id.tz or self.env.user.tz or "UTC"
        holidays = self.env["hr.payslip"]._get_public_holiday_dates(contract, day, day, tzname)
        if day in holidays:
            kind = "public_holiday"
            eligible = employee._is_paid_attendance_public_holiday(day, contract, ignore_withholding=True)
        elif employee._is_attendance_weekly_off(day):
            kind = "weekly_off"
            eligible = employee._is_paid_attendance_weekly_off(day, contract, ignore_withholding=True)
        else:
            return info
        decision = employee._get_paid_day_decision(day, kind)
        return {"kind": kind, "eligible": eligible,
                "withheld": decision.action == "withhold", "reason": decision.reason or ""}

    @api.model
    def set_dashboard_paid_day(self, employee_id, selected_date, kind, action, reason):
        """Append an audited exception; never alter punches or saved extra pay."""
        if not self.env.user.has_group("hr.group_hr_user"):
            raise UserError(_("Only HR officers can change paid-day credit."))
        if kind not in ("weekly_off", "public_holiday") or action not in ("withhold", "restore"):
            raise ValidationError(_("Invalid paid-day decision."))
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError(_("Enter a reason for the paid-day decision."))
        day = fields.Date.to_date(selected_date)
        if not day:
            raise ValidationError(_("Select an attendance date."))
        employee = self.env["hr.employee"].browse(employee_id).exists()
        if not employee:
            raise UserError(_("The employee is not available."))
        employee.check_access("read")
        if employee.company_id not in self.env.companies:
            raise UserError(_("The employee is outside your allowed companies."))
        # Serialize decisions for this employee so concurrent clicks cannot
        # replace one another silently. Audit records are append-only for HR.
        self.env.cr.execute("SELECT id FROM hr_employee WHERE id = %s FOR UPDATE", [employee.id])
        info = self._paid_day_info(employee, day, employee._get_attendance_contract(day))
        latest = employee._get_paid_day_decision(day, kind)
        if action == "withhold":
            if info["kind"] != kind or not info["eligible"]:
                raise UserError(_("This date is not eligible for this paid-day credit."))
            if latest.action == "withhold":
                raise UserError(_("This paid-day credit is already withheld. Refresh the dashboard."))
        elif latest.action != "withhold":
            raise UserError(_("There is no withheld paid-day credit to restore."))
        self.env["bambus.attendance.paid.day.decision"].sudo().create({
            "employee_id": employee.id, "date": day, "kind": kind,
            "action": action, "reason": reason, "actor_id": self.env.uid,
        })
        return self.get_attendance_dashboard(fields.Date.to_string(day))

    @api.model
    def open_dashboard_attendance_entries(self, employee_id, selected_date):
        """Open actual punches using the dashboard's local check-in date."""
        self.env['hr.attendance'].check_access('read')
        employee = self.env['hr.employee'].browse(employee_id).exists()
        if not employee:
            raise UserError(_("The employee is not available."))
        employee.check_access('read')
        day = fields.Date.to_date(selected_date)
        if not day:
            raise ValidationError(_("Select an attendance date."))
        timezone = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        start = timezone.localize(datetime.combine(day, time.min))
        end = timezone.localize(datetime.combine(day + timedelta(days=1), time.min))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Attendance Entries: %(employee)s (%(date)s)", employee=employee.name, date=day),
            'res_model': 'hr.attendance',
            'views': [(False, 'list'), (False, 'form')],
            'target': 'current',
            'domain': [('employee_id', '=', employee.id),
                       ('check_in', '>=', fields.Datetime.to_string(start.astimezone(pytz.UTC).replace(tzinfo=None))),
                       ('check_in', '<', fields.Datetime.to_string(end.astimezone(pytz.UTC).replace(tzinfo=None)))],
            'context': {'default_employee_id': employee.id},
        }

    @api.model
    def get_attendance_dashboard(self, selected_date=None):
        """Read one day's metrics from employees, attendances and time off."""
        day = fields.Date.to_date(selected_date) if selected_date else fields.Date.context_today(self)
        company = self.env.company
        # Use the same employee population as the employee directory. Employee
        # record rules already limit this query to companies the HR user may
        # access; attendance punches must never determine roster membership.
        employee_model = self.env["hr.employee"].with_context(active_test=False)
        all_employees = employee_model.search([('company_id', '=', company.id)])
        employees = all_employees.filtered("active")

        def employee_department(employee):
            """Return the department linked to an already accessible employee.

            Some existing employee records have a department whose company does
            not match the employee company. Department record rules hide that
            relation after a company switch, even though the employee itself is
            correctly visible. Elevated access is limited to resolving this
            employee's linked department for the dashboard.
            """
            return employee.sudo().department_id

        timezone = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")
        local_start = timezone.localize(datetime.combine(day, time.min))
        local_end = timezone.localize(datetime.combine(day + timedelta(days=1), time.min))
        utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
        attendances = self.env["hr.attendance"].search([
            ("employee_id", "in", employees.ids),
            ("check_in", ">=", fields.Datetime.to_string(utc_start)),
            ("check_in", "<", fields.Datetime.to_string(utc_end)),
        ])
        # Keep the dashboard authoritative even when an automation template
        # was changed after punches were imported. Attendance hooks recompute
        # on punch edits, but a policy-only edit otherwise leaves stored fine
        # and overtime snapshots stale until somebody edits an attendance.
        if attendances:
            self.env["hr.attendance.overtime"].sudo().bambus_recompute_range(
                attendances.employee_id.ids, day, day
            )
            attendances = self.env["hr.attendance"].search([
                ("employee_id", "in", employees.ids),
                ("check_in", ">=", fields.Datetime.to_string(utc_start)),
                ("check_in", "<", fields.Datetime.to_string(utc_end)),
            ])
        leaves = self.env["hr.leave"].search([
            ("employee_id", "in", employees.ids),
            ("state", "=", "validate"),
            ("request_date_from", "<=", day),
            ("request_date_to", ">=", day),
        ])
        day_leave_requests = self.env["hr.leave"].search([
            ("employee_id", "in", employees.ids),
            ("state", "in", ["confirm", "validate1", "validate"]),
            ("request_date_from", "<=", day),
            ("request_date_to", ">=", day),
        ], order="id desc")
        leave_by_employee = {}
        for leave in day_leave_requests:
            leave_by_employee.setdefault(leave.employee_id.id, leave)
        upcoming_leaves = self.env["hr.leave"].search([
            ("employee_id", "in", employees.ids),
            ("state", "=", "validate"),
            ("request_date_from", ">", day),
        ])
        attendance_employee_ids = set(attendances.employee_id.ids)
        halfday_employee_ids = {
            leave.employee_id.id for leave in leaves
            if "request_unit_half" in leave._fields and leave.request_unit_half
        }
        leave_employee_ids = set(leaves.employee_id.ids) - halfday_employee_ids
        present_employee_ids = attendance_employee_ids - leave_employee_ids
        unmarked_employee_ids = (
            set(employees.ids) - attendance_employee_ids
            - leave_employee_ids - halfday_employee_ids
        )
        absent_employee_ids = set()
        day_reviews = self.env['bambus.attendance.day.review'].search([
            ('date', '=', day), ('company_id', '=', company.id),
            ('employee_id', 'in', employees.ids),
        ])
        review_by_employee = {line.employee_id.id: line for line in day_reviews}
        # Only an explicit manager status takes precedence. Merely opening an
        # OT/Fine dialog creates a review and must not turn an employee
        # with no punches into Absent/Present.
        for line in day_reviews:
            if not line.attendance_status_manual:
                continue
            employee_id = line.employee_id.id
            present_employee_ids.discard(employee_id)
            unmarked_employee_ids.discard(employee_id)
            halfday_employee_ids.discard(employee_id)
            leave_employee_ids.discard(employee_id)
            absent_employee_ids.discard(employee_id)
            if line.status == "present":
                present_employee_ids.add(employee_id)
            elif line.status == "halfday":
                halfday_employee_ids.add(employee_id)
            elif line.status == "leave":
                leave_employee_ids.add(employee_id)
            else:
                absent_employee_ids.add(employee_id)
        fine_hours = sum(attendances.mapped("bambus_fine_hours")) if "bambus_fine_hours" in attendances._fields else 0.0
        fine_amount = sum(attendances.mapped("bambus_fine_amount")) if "bambus_fine_amount" in attendances._fields else 0.0
        overtime_employee_ids = set(
            attendances.filtered(lambda attendance: attendance.overtime_hours > 0).employee_id.ids
        )
        fine_employee_ids = set()
        if "bambus_fine_hours" in attendances._fields:
            fine_employee_ids = set(
                attendances.filtered(
                    lambda attendance: attendance.bambus_fine_hours > 0
                ).employee_id.ids
            )
        for line in day_reviews:
            has_attendance_basis = (
                line.employee_id.id in attendance_employee_ids or line.attendance_status_manual)
            for kind, selected in [('overtime', overtime_employee_ids), ('fine', fine_employee_ids)]:
                if line[kind + '_state'] in ('approved', 'rejected'):
                    selected.discard(line.employee_id.id)
                    if has_attendance_basis and line[kind + '_state'] == 'approved' and line[kind + '_hours'] > 0:
                        selected.add(line.employee_id.id)
        contracts = self.env["hr.contract"].search([
            ("employee_id", "in", employees.ids),
            ("state", "!=", "cancel"),
            ("date_start", "<=", day),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", day),
        ], order="date_start desc, id desc")
        contract_by_employee = {}
        for contract in contracts:
            contract_by_employee.setdefault(contract.employee_id.id, contract)
        # Derived display statuses only: never create a punch or a leave request.
        paid_status_by_employee = {}
        paid_info_by_employee = {}
        for employee in employees:
            info = self._paid_day_info(employee, day, contract_by_employee.get(employee.id))
            paid_info_by_employee[employee.id] = info
            if employee.id not in unmarked_employee_ids or not info["kind"]:
                continue
            if info["withheld"]:
                paid_status_by_employee[employee.id] = "unpaid_" + info["kind"]
            elif info["eligible"]:
                paid_status_by_employee[employee.id] = "paid_" + info["kind"]
        unmarked_employee_ids.difference_update(paid_status_by_employee)
        departments = []
        department_groups = {}
        for employee in employees:
            department = employee_department(employee)
            key = department.id or 0
            group = department_groups.setdefault(key, {
                "id": key,
                "name": department.display_name or _("No Department"),
                "employee_ids": set(),
            })
            group["employee_ids"].add(employee.id)
        for group in department_groups.values():
            group_employee_ids = group.pop("employee_ids")
            departments.append({
                **group,
                "present": len(group_employee_ids & present_employee_ids),
                "absent": len(group_employee_ids & absent_employee_ids),
                "not_marked": len(group_employee_ids & unmarked_employee_ids),
                "halfday": len(group_employee_ids & halfday_employee_ids),
                "overtime": len(group_employee_ids & overtime_employee_ids),
                "fine": len(group_employee_ids & fine_employee_ids),
                "leave": len(group_employee_ids & leave_employee_ids),
            })
        departments.sort(key=lambda department: department["name"].lower())

        shift_groups = {}
        for employee in employees:
            contract = contract_by_employee.get(employee.id)
            calendar = contract.resource_calendar_id if contract else False
            key = calendar.id if calendar else 0
            group = shift_groups.setdefault(key, {
                "id": key,
                "name": calendar.display_name if calendar else _("No Work Schedule"),
                "employee_ids": set(),
            })
            group["employee_ids"].add(employee.id)
        shifts = []
        for group in shift_groups.values():
            group_employee_ids = group.pop("employee_ids")
            shifts.append({
                **group,
                "present": len(group_employee_ids & present_employee_ids),
                "absent": len(group_employee_ids & absent_employee_ids),
                "not_marked": len(group_employee_ids & unmarked_employee_ids),
                "halfday": len(group_employee_ids & halfday_employee_ids),
                "overtime": len(group_employee_ids & overtime_employee_ids),
                "fine": len(group_employee_ids & fine_employee_ids),
                "leave": len(group_employee_ids & leave_employee_ids),
            })
        shifts.sort(key=lambda shift: shift["name"].lower())

        attendances_by_employee = {}
        for attendance in attendances:
            attendances_by_employee.setdefault(attendance.employee_id.id, []).append(attendance)

        def format_time(value):
            if not value:
                return ""
            local_value = fields.Datetime.context_timestamp(self, value)
            return local_value.strftime("%I:%M %p").lstrip("0")

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
            if not optional_value(attendance, field_name):
                return ""
            return f"/web/image/hr.attendance/{attendance.id}/{field_name}"

        daily_attendance = []
        for employee in employees.sorted(key=lambda item: (item.name or "").lower()):
            employee_attendances = attendances_by_employee.get(employee.id, [])
            override = review_by_employee.get(employee.id)
            day_leave = (
                override.leave_id
                if override and override.leave_id
                else leave_by_employee.get(employee.id, self.env["hr.leave"])
            )
            check_ins = [attendance.check_in for attendance in employee_attendances if attendance.check_in]
            check_outs = [attendance.check_out for attendance in employee_attendances if attendance.check_out]
            if employee.id in leave_employee_ids:
                status = "leave"
                status_label = _("Leave")
            elif employee.id in halfday_employee_ids:
                status = "halfday"
                status_label = _("Half Day")
            elif employee.id in attendance_employee_ids:
                status = "present"
                status_label = _("Present")
            else:
                status = "not_marked"
                status_label = _("Not Marked")
            if status == "not_marked" and employee.id in paid_status_by_employee:
                status = paid_status_by_employee[employee.id]
                status_label = {
                    "paid_public_holiday": _("Paid Public Holiday"),
                    "paid_weekly_off": _("Paid Weekly Off"),
                    "unpaid_public_holiday": _("Unpaid Public Holiday"),
                    "unpaid_weekly_off": _("Unpaid Weekly Off"),
                }[status]
            if override and override.attendance_status_manual:
                status = override.status
                status_label = dict(override._fields["status"].selection).get(status, status)
            contract = contract_by_employee.get(employee.id)
            calendar = contract.resource_calendar_id if contract else False
            contract_type = contract.contract_type_id if contract else False
            wage_type = contract.wage_type if contract and "wage_type" in contract._fields else ""
            automation = employee._get_attendance_automation_template(day)
            employee_fine_hours = 0.0
            if "bambus_fine_hours" in attendances._fields:
                employee_fine_hours = sum(
                    attendance.bambus_fine_hours or 0.0
                    for attendance in employee_attendances
                )
            if employee._fine_only_attendance_context(day) is not None:
                # Whole missing sessions belong to the date-wide proposal;
                # legacy punch fines can omit a session with no punch.
                employee_fine_hours = sum(
                    item['hours'] for item in employee._attendance_exception_components(day).values()
                )
            display_check_in = min(check_ins) if check_ins else False
            display_check_out = max(check_outs) if check_outs else False
            display_worked_hours = sum(a.worked_hours for a in employee_attendances)
            attendance_logs = []
            for attendance in sorted(employee_attendances, key=lambda item: item.check_in):
                local_in = fields.Datetime.context_timestamp(self, attendance.check_in)
                attendance_logs.append({
                    "id": f"{attendance.id}-in",
                    "type": "check_in",
                    "label": _("Punched In"),
                    "time": local_in.strftime("%I:%M %p").lstrip("0"),
                    "mode": attendance_mode(attendance, "in_mode"),
                    "address": optional_value(attendance, "checkin_reverse_address"),
                    "image_url": attendance_image_url(attendance, "recognized_face_checkin"),
                    "actor": employee.name,
                })
                if attendance.check_out:
                    local_out = fields.Datetime.context_timestamp(self, attendance.check_out)
                    attendance_logs.append({
                        "id": f"{attendance.id}-out",
                        "type": "check_out",
                        "label": _("Punched Out"),
                        "time": local_out.strftime("%I:%M %p").lstrip("0"),
                        "mode": attendance_mode(attendance, "out_mode"),
                        "address": optional_value(attendance, "checkout_reverse_address"),
                        "image_url": attendance_image_url(attendance, "recognized_face_checkout"),
                        "actor": employee.name,
                    })
            hr_updates = self.env["bambus.hr.attendance.time.audit"].search([
                ("employee_id", "=", employee.id),
                ("date", "=", day),
            ], order="create_date, id")
            logged_adjustment_types = set(hr_updates.mapped("adjustment_type"))
            for update in hr_updates:
                adjusted_times = []
                if update.adjustment_type == "attendance":
                    if update.previous_check_in or update.check_in:
                        adjusted_times.append(_(
                            "In %s → %s",
                            format_time(update.previous_check_in) or _("Not set"),
                            format_time(update.check_in) or _("Not set"),
                        ))
                    if update.previous_check_out or update.check_out:
                        adjusted_times.append(_(
                            "Out %s → %s",
                            format_time(update.previous_check_out) or _("Not set"),
                            format_time(update.check_out) or _("Not set"),
                        ))
                    label = _("Attendance time adjusted")
                else:
                    hours = max(update.adjusted_hours or 0.0, 0.0)
                    total_minutes = round(hours * 60)
                    previous_minutes = round(max(update.previous_hours or 0.0, 0.0) * 60)
                    adjusted_times.append(_(
                        "%02d:%02d → %02d:%02d hrs",
                        previous_minutes // 60, previous_minutes % 60,
                        total_minutes // 60, total_minutes % 60,
                    ))
                    label = dict(
                        update._fields["adjustment_type"]._description_selection(self.env)
                    ).get(update.adjustment_type)
                if update.change_details:
                    adjusted_times.append(update.change_details)
                attendance_logs.append({
                    "id": f"hr-{update.id}",
                    "type": "hr_update",
                    "label": label,
                    "time": fields.Datetime.context_timestamp(
                        self, update.create_date
                    ).strftime("%I:%M %p").lstrip("0"),
                    "mode": _("HR Update"),
                    "details": " · ".join(adjusted_times),
                    "address": "",
                    "image_url": False,
                    "actor": update.updated_by_id.name,
                })
            # Lines approved before the audit model was introduced still have
            # updater metadata. Surface their latest adjustment once so an
            # existing HR update does not disappear from the Logs popup.
            legacy_updates = (
                ("overtime", _("Overtime adjusted"), "overtime_detected_hours", "overtime_hours",
                 "overtime_updated_by_id", "overtime_updated_on"),
                ("fine", _("Late / Fine adjusted"), "fine_detected_hours", "fine_hours",
                 "fine_updated_by_id", "fine_updated_on"),
                ("hourly_pay", _("Hourly pay adjusted"), "hourly_pay_detected_hours", "hourly_pay_hours",
                 "hourly_pay_updated_by_id", "hourly_pay_updated_on"),
            )
            for kind, label, detected_field, hours_field, user_field, date_field in legacy_updates:
                updated_on = override and override[date_field]
                if not updated_on or kind in logged_adjustment_types:
                    continue
                total_minutes = round(max(override[hours_field] or 0.0, 0.0) * 60)
                detected_minutes = round(max(override[detected_field] or 0.0, 0.0) * 60)
                attendance_logs.append({
                    "id": f"hr-line-{override.id}-{kind}",
                    "type": "hr_update",
                    "label": label,
                    "time": fields.Datetime.context_timestamp(
                        self, updated_on
                    ).strftime("%I:%M %p").lstrip("0"),
                    "mode": _("HR Update"),
                    "details": _(
                        "%02d:%02d → %02d:%02d hrs",
                        detected_minutes // 60, detected_minutes % 60,
                        total_minutes // 60, total_minutes % 60,
                    ),
                    "address": "",
                    "image_url": False,
                    "actor": override[user_field].name,
                })
            raw_overtime_hours = sum(a.overtime_hours for a in employee_attendances)
            overtime_reviewed = bool(
                override and override.overtime_state in ("approved", "rejected")
            )
            fine_reviewed = bool(
                override and override.fine_state in ("approved", "rejected")
            )
            if override and override.overtime_state == "approved":
                employee_overtime_hours = override.overtime_hours
            elif override and override.overtime_state == "rejected":
                employee_overtime_hours = 0.0
            else:
                employee_overtime_hours = raw_overtime_hours
            if override and override.fine_state == "approved":
                employee_fine_hours = override.fine_hours
            elif override and override.fine_state == "rejected":
                employee_fine_hours = 0.0
            employee_overtime_hours = max(employee_overtime_hours, 0.0)
            employee_fine_hours = max(employee_fine_hours, 0.0)
            overtime_enabled = bool(automation and automation.overtime_enabled) or bool(override and override.overtime_re_review_required)
            fine_enabled = bool(
                automation
                and (
                    automation.late_enabled
                    or automation.early_exit_enabled
                    or automation.break_enabled
                )
            )
            fine_enabled = fine_enabled or bool(override and override.fine_re_review_required)
            wage_label, wage_amount = self.env['bambus.hr.attendance.review.wizard']._contract_wage(contract)
            decisions = self.env["bambus.attendance.paid.day.decision"].search([
                ("employee_id", "=", employee.id), ("date", "=", day),
            ], order="id")
            for decision in decisions:
                attendance_logs.append({
                    "id": f"paid-day-{decision.id}", "type": "hr_update",
                    "label": (_("Paid-off Credit Withheld") if decision.action == "withhold"
                              else _("Paid-off Credit Restored")),
                    "time": fields.Datetime.context_timestamp(self, decision.create_date).strftime("%I:%M %p").lstrip("0"),
                    "actor": decision.actor_id.name, "mode": _("HR Decision"),
                    "details": decision.reason, "address": "", "image_url": False,
                })
            paid_info = paid_info_by_employee[employee.id]
            daily_attendance.append({
                "id": employee.id,
                "name": employee.display_name,
                "employee_code": employee.barcode or "",
                "department": employee_department(employee).display_name or _("No Department"),
                "shift": calendar.display_name if calendar else _("No Work Schedule"),
                "contract_type_id": contract_type.id if contract_type else 0,
                "contract_type": contract_type.display_name if contract_type else _("No Contract Type"),
                "contract_wage_label": wage_label,
                "contract_wage_amount": wage_amount,
                "currency_symbol": employee.company_id.currency_id.symbol or "",
                "wage_type": wage_type,
                "is_hourly": wage_type == "hourly",
                "fine_enabled": fine_enabled,
                "overtime_enabled": overtime_enabled,
                "overtime_review_pending": bool(
                    (override and override.overtime_re_review_required) or
                    (overtime_enabled and employee_overtime_hours > 0 and not overtime_reviewed)
                ),
                "fine_review_pending": bool(
                    (override and override.fine_re_review_required) or
                    (fine_enabled and employee_fine_hours > 0 and not fine_reviewed)
                ),
                "hourly_pay_enabled": bool(
                    wage_type == "hourly"
                    and automation.hourly_pay_enabled
                ),
                "hourly_pay_hours": round(
                    override.hourly_pay_hours
                    if override and override.hourly_pay_state == "approved"
                    else display_worked_hours,
                    2,
                ),
                "status": status,
                "status_label": status_label,
                "paid_day_kind": paid_info["kind"],
                "paid_day_eligible": paid_info["eligible"],
                "paid_day_withheld": paid_info["withheld"],
                "paid_day_reason": paid_info["reason"],
                "check_in": format_time(display_check_in),
                "check_out": format_time(display_check_out),
                "check_in_value": fields.Datetime.context_timestamp(self, display_check_in).strftime("%H:%M") if display_check_in else "",
                "check_out_value": fields.Datetime.context_timestamp(self, display_check_out).strftime("%H:%M") if display_check_out else "",
                "overtime_hours": round(employee_overtime_hours, 2),
                "fine_hours": round(employee_fine_hours, 2),
                "worked_hours": round(display_worked_hours, 2),
                "has_attendance": bool(employee_attendances),
                "line_id": override.id if override else False,
                "leave_id": day_leave.id or False,
                "leave_is_half_day": bool(day_leave and getattr(day_leave, "request_unit_half", False)),
                "logs": attendance_logs,
            })
        return {
            "date": fields.Date.to_string(day),
            "company": company.display_name,
            "departments": departments,
            "shifts": shifts,
            "daily_attendance": daily_attendance,
            "metrics": {
                "total": len(employees),
                "present": len(present_employee_ids),
                "absent": len(absent_employee_ids),
                "halfday": len(halfday_employee_ids),
                "leave": len(leave_employee_ids),
                "punched_in": len(attendance_employee_ids),
                "punched_out": len(set(attendances.filtered("check_out").employee_id.ids)),
                "not_marked": len(unmarked_employee_ids),
                "upcoming_leaves": len(set(upcoming_leaves.employee_id.ids)),
                "overtime": round(sum(row["overtime_hours"] for row in daily_attendance), 2),
                "fine": round(sum(row["fine_hours"] for row in daily_attendance), 2),
                "overtime_review_count": sum(
                    1 for row in daily_attendance if row["overtime_review_pending"]
                ),
                "fine_review_count": sum(
                    1 for row in daily_attendance if row["fine_review_pending"]
                ),
                "fine_amount": round(fine_amount, 2),
                "on_duty": 0,
                "upcoming_on_duty": 0,
                "deactivated": len(all_employees - employees),
                "daily_work_entries": len(attendances),
            },
        }

    @api.model
    def _day_review(self, employee, day, create=False):
        employee.check_access('read')
        if employee.company_id != self.env.company:
            raise UserError(_('Select the employee company before updating attendance.'))
        model = self.env['bambus.attendance.day.review']
        review = model.search([('employee_id', '=', employee.id),
            ('company_id', '=', employee.company_id.id), ('date', '=', day)], limit=1)
        if create and not review:
            review = model.create({'employee_id': employee.id,
                'company_id': employee.company_id.id, 'date': day})
        return review

    @api.model
    def update_dashboard_attendance(self, employee_id, selected_date, values):
        """Persist time edits as real punches and status decisions independently."""
        if not self.env.user.has_group('hr.group_hr_user'):
            raise UserError(_('Only HR officers can update employee attendance.'))
        employee = self.env['hr.employee'].browse(employee_id).exists()
        day = fields.Date.to_date(selected_date)
        if not employee or not day:
            raise UserError(_('Select an employee and attendance date.'))
        line = self._day_review(employee, day, create=True)
        line._check_review_access()
        status = values.get('status', 'not_marked')
        if status not in {'present', 'absent', 'halfday', 'leave', 'not_marked'}:
            raise UserError(_('Select a valid attendance status.'))
        status_manual = bool(values.get('status_manual', 'status' in values))
        if 'status' in values or 'status_manual' in values:
            line.write({'status': status if status != 'not_marked' else 'absent',
                'attendance_status_manual': status_manual})
        previous_check_in, previous_check_out = line.check_in, line.check_out
        if 'check_in' in values or 'check_out' in values:
            tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
            def parse(value):
                if not value:
                    return False
                try:
                    local = tz.localize(datetime.combine(day, datetime.strptime(value, '%H:%M').time()))
                except (ValueError, TypeError):
                    raise UserError(_('Enter time in HH:MM format.'))
                return local.astimezone(pytz.UTC).replace(tzinfo=None)
            check_in = parse(values['check_in']) if 'check_in' in values else previous_check_in
            check_out = parse(values['check_out']) if 'check_out' in values else previous_check_out
            if check_out and not check_in:
                raise UserError(_('Enter a check-in before setting checkout.'))
            if check_in and check_out and check_out < check_in:
                check_out += timedelta(days=1)
            punches = line._review_attendances()
            if punches:
                first = punches[0]
                last = max(punches, key=lambda att: att.check_out or att.check_in)
                if not check_in:
                    raise UserError(_('Use the pencil attendance list to remove punch records.'))
                if first == last:
                    first.write({'check_in': check_in, 'check_out': check_out})
                else:
                    # Keep lunch/session gaps and all intermediate punches intact.
                    if 'check_in' in values:
                        first.write({'check_in': check_in})
                    if 'check_out' in values:
                        last.write({'check_out': check_out})
            elif check_in:
                self.env['hr.attendance'].create({'employee_id': employee.id,
                    'check_in': check_in, 'check_out': check_out})
        # Money and final adjustment hours are saved only by their review
        # wizards, never incidentally by a status/time change.
        line._compute_day_data()
        return {'line_id': line.id, 'status': line.status if line.attendance_status_manual else 'not_marked',
            'worked_hours': line.worked_hours}

    @api.model
    def open_dashboard_adjustment(self, employee_id, selected_date, adjustment):
        """Open an overtime, fine, or hourly-pay review from the dashboard."""
        if not self.env.user.has_group("hr.group_hr_user"):
            raise UserError(_("Only HR officers can update employee attendance."))
        if adjustment not in {"overtime", "fine", "hourly_pay"}:
            raise UserError(_("Select overtime, late/fine, or hourly pay."))

        day = fields.Date.to_date(selected_date)
        employee = self.env["hr.employee"].browse(employee_id).exists()
        if not employee or employee.company_id != self.env.company:
            raise UserError(_("The employee is not available for the selected company."))
        contract = self.env["hr.contract"].search([
            ("employee_id", "=", employee.id),
            ("state", "!=", "cancel"),
            ("date_start", "<=", day),
            "|", ("date_end", "=", False), ("date_end", ">=", day),
        ], order="date_start desc, id desc", limit=1)
        template = employee._get_attendance_automation_template(day)

        line = self._day_review(employee, day, create=True)
        self.env['hr.attendance.overtime'].sudo().bambus_recompute_range(employee.ids, day, day)
        line._compute_day_data()

        if adjustment == "overtime":
            return line.action_edit_overtime()
        if adjustment == "fine":
            return line.action_edit_fine()
        if not contract or contract.wage_type != "hourly":
            raise UserError(_("Hourly pay review is only available for hourly contracts."))
        if not template.hourly_pay_enabled:
            raise UserError(_("Enable Hourly Pay Review on the employee's automation template."))
        return line.action_edit_hourly_pay()

    @api.model
    def get_dashboard_adjustment(self, employee_id, selected_date, adjustment):
        """Return the small dashboard-facing adjustment editor payload."""
        action = self.open_dashboard_adjustment(
            employee_id, selected_date, adjustment
        )
        wizard_model = action.get("res_model")
        wizard = self.env[wizard_model].with_context(
            **action.get("context", {})
        ).create({})
        if not wizard:
            raise UserError(_("The attendance adjustment could not be prepared."))

        prefix = {"overtime": "overtime", "fine": "fine", "hourly_pay": "hourly_pay"}[adjustment]
        hours_field = f"{prefix}_hours"
        detected_field = f"detected_{prefix}_hours"
        amount_field = f"{prefix}_amount"
        note_field = "reason" if adjustment == "fine" else "note"
        currency = wizard.currency_id
        rate_helper = self.env["bambus.hr.overtime.wizard"]
        daily_rate, hourly_rate = rate_helper._contract_rates(wizard.line_id)
        wage_label, wage_amount = self.env['bambus.hr.attendance.review.wizard']._contract_wage(wizard.line_id.contract_id)
        return {
            "wizard_id": wizard.id,
            "adjustment": adjustment,
            "employee": wizard.employee_id.name,
            "contract_wage_label": wage_label,
            "contract_wage_amount": wage_amount,
            "date": fields.Date.to_string(wizard.date),
            "detected_hours": wizard[detected_field],
            "hours": wizard[hours_field],
            "calculation_type": wizard.calculation_type,
            "calculation_options": wizard._fields["calculation_type"]._description_selection(
                self.env
            ),
            "rate": wizard.rate,
            "resolved_rate": wizard.resolved_rate if adjustment == "overtime" else 0.0,
            "salary_per_minute": (
                wizard.salary_per_minute if adjustment == "fine" else 0.0
            ),
            "daily_rate": daily_rate,
            "hourly_rate": hourly_rate,
            "amount": wizard[amount_field],
            "note": wizard[note_field] or "",
            "currency": {
                "symbol": currency.symbol or "",
                "position": currency.position or "before",
                "decimal_places": currency.decimal_places,
            },
        }

    @api.model
    def save_dashboard_adjustment(self, wizard_id, adjustment, values):
        """Validate and save a dashboard adjustment through its existing wizard."""
        if not self.env.user.has_group("hr.group_hr_user"):
            raise UserError(_("Only HR officers can update employee attendance."))
        if adjustment not in {"overtime", "fine", "hourly_pay"}:
            raise UserError(_("Select overtime, late/fine, or hourly pay."))

        model_name = {
            "overtime": "bambus.hr.overtime.wizard",
            "fine": "bambus.hr.fine.wizard",
            "hourly_pay": "bambus.hr.hourly.pay.wizard",
        }[adjustment]
        wizard = self.env[model_name].browse(wizard_id).exists()
        if not wizard or wizard.create_uid != self.env.user:
            raise UserError(_("This attendance adjustment has expired. Open it again."))

        hours_field = {
            "overtime": "overtime_hours", "fine": "fine_hours",
            "hourly_pay": "hourly_pay_hours",
        }[adjustment]
        note_field = "reason" if adjustment == "fine" else "note"
        allowed_types = dict(
            wizard._fields["calculation_type"]._description_selection(self.env)
        )
        calculation_type = values.get("calculation_type")
        if calculation_type not in allowed_types:
            raise UserError(_("Select a valid calculation type."))
        try:
            hours = float(values.get("hours", 0.0))
            rate = float(values.get("rate", 0.0))
        except (TypeError, ValueError):
            raise UserError(_("Enter valid hours and rate values."))

        wizard.write({
            hours_field: hours,
            "calculation_type": calculation_type,
            "rate": rate,
            note_field: values.get("note") or False,
        })
        wizard.action_save()
        return {
            "hours": wizard[hours_field],
            "amount": (
                wizard.overtime_amount
                if adjustment == "overtime"
                else wizard.fine_amount if adjustment == "fine"
                else wizard.hourly_pay_amount
            ),
        }

    @api.model
    def create_half_day_leave(self, employee_id, selected_date):
        """Compatibility endpoint: open confirmation, never silently create AM leave."""
        return self.prepare_half_day_leave(employee_id, selected_date)

    @api.model
    def revoke_dashboard_status(self, employee_id, selected_date, status):
        """Remove an HR override and cancel its one-day leave, when applicable."""
        if not self.env.user.has_group("hr.group_hr_user"):
            raise UserError(_("Only HR officers can revoke employee attendance statuses."))
        if status not in {"absent", "halfday", "leave"}:
            raise UserError(_("Only absent and leave statuses can be revoked."))

        day = fields.Date.to_date(selected_date)
        employee = self.env["hr.employee"].browse(employee_id).exists()
        if not employee:
            raise UserError(_("The employee is not available."))
        leave = self.env["hr.leave"].sudo().search([
            ("employee_id", "=", employee.id),
            ("state", "not in", ["refuse", "cancel"]),
            ("request_date_from", "<=", day),
            ("request_date_to", ">=", day),
        ], order="id desc", limit=1)
        if status in {"halfday", "leave"} and leave:
            is_half_day = bool(getattr(leave, "request_unit_half", False))
            if (status == "halfday") != is_half_day:
                raise UserError(_("The selected status does not match the existing time off request."))
            if leave.request_date_from != day or leave.request_date_to != day:
                raise UserError(_("Open Time Off to modify a request that covers multiple days."))
            if leave.state not in {"draft", "refuse", "cancel"}:
                leave.action_refuse()
            if leave.state != "cancel":
                # Odoo 18 has no draft state for hr.leave and refuses to unlink
                # refused requests. Keep the audit record and mark it Cancelled;
                # the refusal above already removes its calendar allocation.
                leave.with_context(mail_notrack=True).write({"state": "cancel"})

        line = self._day_review(employee, day)
        if line:
            line.write({'attendance_status_manual': False})
        return True
