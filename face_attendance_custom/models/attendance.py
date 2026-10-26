from odoo import api, fields, models
from .employee import build_google_maps_route_url


class HrAttendanceInherit(models.Model):
    _inherit = "hr.attendance"
    
    recognized_face_checkin=fields.Image("Recognized Face Check-In",max_width=320,max_height=240)
    recognized_face_checkout=fields.Image("Recognized Face Check-Out",max_width=320,max_height=240)
    attendance_client_id=fields.Char("Attendance client ID")
    checkin_address = fields.Char("Check-In Address")
    checkout_address = fields.Char("Check-Out Address")
    track_employee = fields.Boolean(related="employee_id.track_employee", string="Track Employee")
    location_track_logs = fields.Text("Location Track Logs")
    tracking_route_url = fields.Char("Open tracking route", compute="_compute_tracking_route_url")

    expected_checkout_time = fields.Datetime("Expected Checkout Time", compute="_compute_expected_checkout_time")

    @api.depends("location_track_logs", "in_latitude", "in_longitude", "out_latitude", "out_longitude")
    def _compute_tracking_route_url(self):
        import json
        for record in self:
            coords = []
            if record.location_track_logs:
                try:
                    data = json.loads(record.location_track_logs)
                    if isinstance(data, list):
                        for item in data:
                            c = item.get("coordinates") if isinstance(item, dict) else item
                            if isinstance(c, (list, tuple)) and len(c) >= 2:
                                if c[0] or c[1]:
                                    coords.append((c[0], c[1]))
                except Exception:
                    pass
            if not coords:
                if record.in_latitude and record.in_longitude:
                    coords.append((record.in_latitude, record.in_longitude))
                if record.out_latitude and record.out_longitude and (record.out_latitude != record.in_latitude or record.out_longitude != record.in_longitude):
                    coords.append((record.out_latitude, record.out_longitude))

            record.tracking_route_url = build_google_maps_route_url(coords)

    def _summarize_location_track_logs(self):
        import json
        import pytz
        for record in self:
            if not record.employee_id or not record.check_in or not record.check_out:
                continue

            logs = self.env["hr.employee.location.log"].sudo().search([
                ("employee_id", "=", record.employee_id.id),
                ("timestamp", ">=", record.check_in),
                ("timestamp", "<=", record.check_out),
            ], order="timestamp asc, id asc")

            if not logs and not record.employee_id.track_employee:
                continue

            if not logs and record.location_track_logs:
                try:
                    existing_data = json.loads(record.location_track_logs)
                    if isinstance(existing_data, list) and len(existing_data) > 2:
                        # Rich route with intermediate waypoints already provided by offline-first mobile app! Preserve it!
                        continue
                except Exception:
                    pass

            tz_name = record.employee_id.resource_calendar_id.tz or self.env.user.tz or "UTC"
            try:
                tz = pytz.timezone(tz_name)
            except Exception:
                tz = pytz.utc

            summary = []
            if logs:
                for log in logs:
                    log_utc = log.timestamp.replace(tzinfo=pytz.utc)
                    local_time = log_utc.astimezone(tz).strftime("%d-%m-%Y %H:%M:%S")
                    summary.append({
                        "timestamp": local_time,
                        "coordinates": [log.latitude, log.longitude]
                    })
            else:
                if record.in_latitude and record.in_longitude:
                    in_time = record.check_in.replace(tzinfo=pytz.utc).astimezone(tz).strftime("%d-%m-%Y %H:%M:%S")
                    summary.append({
                        "timestamp": in_time,
                        "coordinates": [record.in_latitude, record.in_longitude]
                    })
                if record.out_latitude and record.out_longitude and (record.out_latitude != record.in_latitude or record.out_longitude != record.in_longitude):
                    out_time = record.check_out.replace(tzinfo=pytz.utc).astimezone(tz).strftime("%d-%m-%Y %H:%M:%S")
                    summary.append({
                        "timestamp": out_time,
                        "coordinates": [record.out_latitude, record.out_longitude]
                    })

            if summary:
                record.location_track_logs = json.dumps(summary)

    def write(self, vals):
        res = super().write(vals)
        if "check_out" in vals and vals.get("check_out"):
            self._summarize_location_track_logs()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.check_out:
                rec._summarize_location_track_logs()
        return records

    def _compute_expected_checkout_time(self):
        import pytz
        from datetime import timedelta
        for record in self:
            if not record.check_in or not record.employee_id:
                record.expected_checkout_time = False
                continue
            
            calendar = record.employee_id.resource_calendar_id
            if not calendar:
                record.expected_checkout_time = record.check_in + timedelta(hours=8)
                continue
                
            fallback_hours = calendar.hours_per_day if hasattr(calendar, 'hours_per_day') and calendar.hours_per_day else 8.0
            
                
            tz_name = calendar.tz or self.env.user.tz or 'UTC'
            tz = pytz.timezone(tz_name)
            
            check_in_utc = record.check_in.replace(tzinfo=pytz.utc)
            check_in_local = check_in_utc.astimezone(tz)
            
            day_of_week = str(check_in_local.weekday())
            day_attendances = calendar.attendance_ids.filtered(lambda a: a.dayofweek == day_of_week)
            
            if not day_attendances:
                record.expected_checkout_time = record.check_in + timedelta(hours=fallback_hours)
                continue
                
            max_hour_to = max(day_attendances.mapped('hour_to'))
            hours = int(max_hour_to)
            minutes = int((max_hour_to - hours) * 60)
            
            checkout_local = check_in_local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            if checkout_local <= check_in_local:
                # Checked in after shift ends, fallback to standard daily hours
                record.expected_checkout_time = record.check_in + timedelta(hours=fallback_hours)
            else:
                record.expected_checkout_time = checkout_local.astimezone(pytz.utc).replace(tzinfo=None)
