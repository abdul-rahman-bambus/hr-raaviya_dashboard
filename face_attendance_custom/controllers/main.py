from odoo.http import request
from odoo import http, _
from odoo.exceptions import AccessError

class PortalCalendar(http.Controller):

    @staticmethod
    def _get_company(company_id=None):
        if company_id:
            return request.env["res.company"].sudo().browse(company_id).exists()
        return request.env.company.sudo()

    @staticmethod
    def _get_current_employee(company=None, allow_company_fallback=True):
        user = request.env.user.sudo()
        employee_env = request.env["hr.employee"].sudo()

        if company:
            employee = employee_env.search(
                [
                    ("user_id", "=", user.id),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )
            if employee:
                return employee

        if company:
            employee = user.with_company(company).employee_id.sudo().exists()
            if employee:
                return employee
            if not allow_company_fallback:
                return employee_env
        else:
            employee = user.with_company(request.env.company).employee_id.sudo().exists()
            if employee:
                return employee

        return employee_env.search([("user_id", "=", user.id)], limit=1)

    @staticmethod
    def _can_manage_all_attendances():
        user = request.env.user
        return (
            user.has_group("hr_attendance.group_hr_attendance_officer")
            or user.has_group("hr_attendance.group_hr_attendance_manager")
        )

    @staticmethod
    def _get_target_employee(employee_id, current_employee, can_manage_all, company=None):
        if can_manage_all and employee_id:
            employee = request.env["hr.employee"].sudo().browse(employee_id).exists()
            if company and employee.company_id != company:
                return request.env["hr.employee"]
            return employee
        if employee_id and employee_id != current_employee.id:
            return request.env["hr.employee"]
        if company and current_employee.company_id != company:
            return request.env["hr.employee"]
        return current_employee

    @staticmethod
    def _resolve_company(kw, current_employee=None):
        company_id = kw.get("company_id")
        company = PortalCalendar._get_company(company_id)
        if company:
            return company
        if current_employee:
            return current_employee.company_id.sudo()
        return request.env.company.sudo()

    @staticmethod
    def _prepare_employee_values(employee_data):
        allowed_fields = (
            "image_128",
            "image_256",
            "image_512",
            "image_1024",
            "image_1920",
            "is_enrolled",
            "last_photo_update_time",
        )
        return {
            field_name: employee_data.get(field_name)
            for field_name in allowed_fields
            if field_name in employee_data
        }

    @staticmethod
    def _prepare_attendance_values(attendance_data, employee_id):
        allowed_fields = (
            "check_in",
            "check_out",
            "recognized_face_checkin",
            "recognized_face_checkout",
            "attendance_client_id",
            "in_latitude",
            "in_longitude",
            "out_latitude",
            "out_longitude",
            "in_mode",
            "out_mode"
        )
        values = {
            field_name: attendance_data.get(field_name)
            for field_name in allowed_fields
            if field_name in attendance_data
        }
        values["employee_id"] = employee_id
        return values

    @http.route(["/face_attendance"], type="json", auth="user")
    def portal_check_user(self, **kw):
        can_manage_all = self._can_manage_all_attendances()
        company = self._resolve_company(kw)
        has_explicit_company = bool(kw.get("company_id"))
        current_employee = self._get_current_employee(
            company,
            allow_company_fallback=not has_explicit_company,
        )

        if not current_employee and not can_manage_all:
            raise AccessError(_("The current user is not linked to an employee."))

        if current_employee and not has_explicit_company:
            company = current_employee.company_id.sudo()

        Attendance = request.env["hr.attendance"].sudo().with_company(company)

        employees = kw.get("employees") or []
        for employee_data in employees:
            employee_company = self._get_company(employee_data.get("company_id")) or company
            target_employee = self._get_target_employee(
                employee_data.get("odoo_id"), current_employee, can_manage_all, employee_company
            )
            if not target_employee:
                continue
            values = self._prepare_employee_values(employee_data)
            if values:
                target_employee.with_company(target_employee.company_id).write(values)

        deleted_ids = []
        old_attendances = kw.get("update_attendance") or []
        for old_attendance in old_attendances:
            domain = [("id", "=", old_attendance.get("odoo_id"))]
            if not can_manage_all:
                domain.append(("employee_id", "=", current_employee.id))
                domain.append(("employee_id.company_id", "=", company.id))
            attendance = Attendance.search(domain, limit=1)
            if not attendance:
                if old_attendance.get("odoo_id"):
                    deleted_ids.append(old_attendance.get("odoo_id"))
                continue

            values = {
                field_name: old_attendance.get(field_name)
                for field_name in ("check_out", "recognized_face_checkout", "out_latitude", "out_longitude", "out_mode")
                if field_name in old_attendance
            }
            if values:
                attendance.with_company(attendance.employee_id.company_id).write(values)

        new_attendances = kw.get("create_attendance") or []
        attendance_ids = Attendance.browse()
        for attendance_data in new_attendances:
            client_id = attendance_data.get("attendance_client_id")
            if not client_id:
                continue

            attendance_company = self._get_company(attendance_data.get("company_id")) or company
            target_employee = self._get_target_employee(
                attendance_data.get("employee_id"), current_employee, can_manage_all, attendance_company
            )
            if not target_employee:
                continue

            values = self._prepare_attendance_values(attendance_data, target_employee.id)
            attendance_env = Attendance.with_company(target_employee.company_id)
            existing = attendance_env.search(
                [
                    ("attendance_client_id", "=", client_id),
                    ("employee_id", "=", target_employee.id),
                ],
                limit=1,
            )

            if existing:
                existing.write(values)
                attendance_ids |= existing
            else:
                attendance_ids |= attendance_env.create(values)

        return {
            "new_attendance_ids": attendance_ids.ids,
            "deleted_attendance_ids": deleted_ids,
        }
