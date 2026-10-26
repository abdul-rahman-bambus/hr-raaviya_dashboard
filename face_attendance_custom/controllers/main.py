from odoo.http import request
from odoo import http, _, fields
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
            getattr(request.env, "is_admin", lambda: False)()
            or getattr(user, "_is_admin", lambda: False)()
            or user.has_group("base.group_system")
            or user.has_group("base.group_erp_manager")
            or user.has_group("hr_attendance.group_hr_attendance_officer")
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
            "track_employee",
            "track_latitude",
            "track_longitude",
            "track_last_updated_at",
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
            "checkin_address",
            "checkout_address",
            "in_mode",
            "out_mode",
            "location_track_logs"
        )
        values = {
            field_name: attendance_data.get(field_name)
            for field_name in allowed_fields
            if field_name in attendance_data
        }
        values["employee_id"] = employee_id
        return values

    @staticmethod
    def _prepare_open_attendance_update_values(attendance_data):
        allowed_fields = (
            "recognized_face_checkin",
            "recognized_face_checkout",
            "attendance_client_id",
            "in_latitude",
            "in_longitude",
            "out_latitude",
            "out_longitude",
            "checkin_address",
            "checkout_address",
            "in_mode",
            "out_mode",
            "check_out",
            "location_track_logs",
        )
        return {
            field_name: attendance_data.get(field_name)
            for field_name in allowed_fields
            if field_name in attendance_data
        }

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
                for field_name in (
                    "check_out",
                    "recognized_face_checkout",
                    "out_latitude",
                    "out_longitude",
                    "checkin_address",
                    "checkout_address",
                    "out_mode",
                    "location_track_logs",
                )
                if field_name in old_attendance
            }
            if values:
                attendance.with_company(attendance.employee_id.company_id).write(values)

        new_attendances = kw.get("create_attendance") or []
        attendance_ids = Attendance.browse()
        attendance_ids_by_client_id = {}
        for attendance_data in new_attendances:
            client_id = attendance_data.get("attendance_client_id")

            attendance_company = self._get_company(attendance_data.get("company_id")) or company
            target_employee = self._get_target_employee(
                attendance_data.get("employee_id"), current_employee, can_manage_all, attendance_company
            )
            if not target_employee:
                continue

            values = self._prepare_attendance_values(attendance_data, target_employee.id)
            attendance_env = Attendance.with_company(target_employee.company_id)
            existing = attendance_env.browse()
            matched_by_client_id = False
            if client_id:
                existing = attendance_env.search(
                    [
                        ("attendance_client_id", "=", client_id),
                        ("employee_id", "=", target_employee.id),
                    ],
                    limit=1,
                )
                matched_by_client_id = bool(existing)

            if not existing:
                existing = attendance_env.search(
                    [
                        ("employee_id", "=", target_employee.id),
                        ("check_out", "=", False),
                    ],
                    order="check_in desc",
                    limit=1,
                )

            if existing:
                update_values = values if matched_by_client_id else self._prepare_open_attendance_update_values(attendance_data)
                if update_values:
                    existing.write(update_values)
                attendance_ids |= existing
                if client_id:
                    attendance_ids_by_client_id[client_id] = existing.id
            else:
                created_attendance = attendance_env.create(values)
                attendance_ids |= created_attendance
                if client_id:
                    attendance_ids_by_client_id[client_id] = created_attendance.id

        return {
            "new_attendance_ids": attendance_ids.ids,
            "new_attendance_ids_by_client_id": attendance_ids_by_client_id,
            "deleted_attendance_ids": deleted_ids,
        }

    @http.route(["/face_attendance/update_live_location"], type="json", auth="public")
    def update_live_location(self, employee_id=None, latitude=None, longitude=None, **kw):
        print("coming live")
        if not employee_id:
            if request.session.uid:
                employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.session.uid)], limit=1)
            else:
                employee = request.env['hr.employee']
        else:
            try:
                employee = request.env['hr.employee'].sudo().browse(int(employee_id)).exists()
            except (ValueError, TypeError):
                employee = request.env['hr.employee']

        if not employee:
            return {"status": "error", "message": "Employee not found"}

        if not employee.track_employee:
            return {"status": "ignored", "message": "Employee tracking is disabled"}

        if latitude is None or longitude is None:
            return {"status": "error", "message": "Missing coordinates"}

        now = fields.Datetime.now()
        recorded_timestamp = kw.get('timestamp')
        log_time = now
        if recorded_timestamp:
            try:
                import datetime
                if isinstance(recorded_timestamp, (int, float)):
                    log_time = datetime.datetime.utcfromtimestamp(recorded_timestamp / 1000.0)
                else:
                    log_time = fields.Datetime.to_datetime(recorded_timestamp)
            except Exception:
                log_time = now

        lat_val = float(latitude)
        lng_val = float(longitude)

        employee.sudo().write({
            "track_latitude": lat_val,
            "track_longitude": lng_val,
            "track_last_updated_at": now,
        })

        # Record historical location log entry
        try:
            request.env['hr.employee.location.log'].sudo().create({
                'employee_id': employee.id,
                'latitude': lat_val,
                'longitude': lng_val,
                'timestamp': log_time,
            })
        except Exception:
            pass

        # Broadcast real-time location update to open employee forms
        try:
            request.env['bus.bus'].sudo()._sendone(
                f'hr_employee_tracking_{employee.id}',
                'hr_employee_tracking/update',
                {
                    'employee_id': employee.id,
                    'latitude': lat_val,
                    'longitude': lng_val,
                    'timestamp': fields.Datetime.to_string(now),
                }
            )
        except Exception:
            pass

        return {
            "status": "success",
            "latitude": lat_val,
            "longitude": lng_val,
            "last_updated_at": fields.Datetime.to_string(now),
        }

    @http.route(["/face_attendance/batch_update_location_logs"], type="json", auth="public")
    def batch_update_location_logs(self, employee_id=None, waypoints=None, **kw):
        if not employee_id:
            if request.session.uid:
                employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.session.uid)], limit=1)
            else:
                employee = request.env['hr.employee']
        else:
            try:
                employee = request.env['hr.employee'].sudo().browse(int(employee_id)).exists()
            except (ValueError, TypeError):
                employee = request.env['hr.employee']

        if not employee:
            return {"status": "error", "message": "Employee not found"}

        if not employee.track_employee:
            return {"status": "ignored", "message": "Employee tracking is disabled"}

        if not waypoints or not isinstance(waypoints, list):
            return {"status": "error", "message": "No waypoints provided"}

        LocationLog = request.env['hr.employee.location.log'].sudo()
        logs_to_create = []
        latest_time = None
        latest_lat = None
        latest_lng = None

        for wp in waypoints:
            try:
                lat = float(wp.get('latitude'))
                lng = float(wp.get('longitude'))
                ts = wp.get('timestamp')
                log_time = fields.Datetime.now()
                if ts:
                    try:
                        import datetime
                        if isinstance(ts, (int, float)):
                            log_time = datetime.datetime.utcfromtimestamp(ts / 1000.0)
                        else:
                            log_time = fields.Datetime.to_datetime(ts)
                    except Exception:
                        log_time = fields.Datetime.now()

                logs_to_create.append({
                    'employee_id': employee.id,
                    'latitude': lat,
                    'longitude': lng,
                    'timestamp': log_time,
                })

                if latest_time is None or log_time > latest_time:
                    latest_time = log_time
                    latest_lat = lat
                    latest_lng = lng
            except Exception:
                continue

        if logs_to_create:
            LocationLog.create(logs_to_create)

        if latest_lat is not None and latest_lng is not None:
            employee.sudo().write({
                "track_latitude": latest_lat,
                "track_longitude": latest_lng,
                "track_last_updated_at": latest_time or fields.Datetime.now(),
            })
            try:
                request.env['bus.bus'].sudo()._sendone(
                    f'hr_employee_tracking_{employee.id}',
                    'hr_employee_tracking/update',
                    {
                        'employee_id': employee.id,
                        'latitude': latest_lat,
                        'longitude': latest_lng,
                        'timestamp': fields.Datetime.to_string(latest_time or fields.Datetime.now()),
                    }
                )
            except Exception:
                pass

        return {
            "status": "success",
            "count": len(logs_to_create),
        }

    @http.route(
        ["/face_attendance/get_live_route", "/face_attendance/get_today_location_logs"],
        type="json",
        auth="public",
    )
    def get_live_route(self, employee_id=None, **kw):
        if not employee_id:
            if request.session.uid:
                employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.session.uid)], limit=1)
            else:
                employee = request.env['hr.employee']
        else:
            try:
                employee = request.env['hr.employee'].sudo().browse(int(employee_id)).exists()
            except (ValueError, TypeError):
                employee = request.env['hr.employee']

        if not employee:
            return {"status": "error", "message": "Employee not found", "points": [], "is_checked_in": False}

        # Check attendance state (active open attendance where check_out is False)
        open_attendance = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False)
        ], limit=1, order='check_in desc')

        is_checked_in = bool(open_attendance)
        points = []

        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        logs = request.env['hr.employee.location.log'].sudo().search([
            ('employee_id', '=', employee.id),
            ('timestamp', '>=', today_start)
        ], order='timestamp asc')

        for log in logs:
            points.append({
                'latitude': log.latitude,
                'longitude': log.longitude,
                'timestamp': fields.Datetime.to_string(log.timestamp),
            })

        return {
            "status": "success",
            "is_checked_in": is_checked_in,
            "check_in": fields.Datetime.to_string(open_attendance.check_in) if is_checked_in and open_attendance.check_in else False,
            "track_latitude": employee.track_latitude,
            "track_longitude": employee.track_longitude,
            "track_last_updated_at": fields.Datetime.to_string(employee.track_last_updated_at) if employee.track_last_updated_at else False,
            "track_map_url": employee.track_map_url,
            "tracking_route_url": employee.tracking_route_url,
            "points": points,
        }

