from odoo import api, models, fields


def build_google_maps_route_url(coords_list):
    """Generate official Google Maps walking route URL for coordinate points."""
    if not coords_list:
        return False
    valid_coords = [c for c in coords_list if c and (c[0] != 0 or c[1] != 0)]
    if not valid_coords:
        return False
    if len(valid_coords) == 1:
        lat, lng = valid_coords[0]
        return f"https://www.google.com/maps?q={lat},{lng}"
    
    start_lat, start_lng = valid_coords[0]
    end_lat, end_lng = valid_coords[-1]
    
    if len(valid_coords) == 2:
        return f"https://www.google.com/maps/dir/?api=1&origin={start_lat},{start_lng}&destination={end_lat},{end_lng}&travelmode=walking"
    
    intermediate = valid_coords[1:-1]
    if len(intermediate) <= 8:
        sampled = intermediate
    else:
        step = (len(intermediate) - 1) / 7.0
        sampled = [intermediate[int(round(i * step))] for i in range(8)]
    
    waypoints_str = "|".join([f"{pt[0]},{pt[1]}" for pt in sampled])
    return f"https://www.google.com/maps/dir/?api=1&origin={start_lat},{start_lng}&destination={end_lat},{end_lng}&waypoints={waypoints_str}&travelmode=walking"


class HrAEmployeeInherit(models.Model):
    _inherit = "hr.employee"
    
    is_enrolled=fields.Boolean("Is Enrolled")
    last_photo_update_time=fields.Datetime("Last photo update time",default=fields.Datetime.now())
    has_employee_tracking = fields.Boolean(related="company_id.employee_tracking", string="Employee Tracking Enabled")
    track_employee = fields.Boolean("Track Employee", default=False)
    track_latitude = fields.Float("Track Latitude", digits=(10, 7))
    track_longitude = fields.Float("Track Longitude", digits=(10, 7))
    track_last_updated_at = fields.Datetime("Last Location Update")
    track_map_url = fields.Char("Open in Maps", compute="_compute_track_map_url")
    tracking_route_url = fields.Char("Open tracking route", compute="_compute_tracking_route_url")
    location_log_ids = fields.One2many("hr.employee.location.log", "employee_id", string="Location Logs")

    @api.depends("track_latitude", "track_longitude")
    def _compute_track_map_url(self):
        for record in self:
            if record.track_latitude and record.track_longitude:
                record.track_map_url = f"https://www.google.com/maps?q={record.track_latitude},{record.track_longitude}"
            else:
                record.track_map_url = False

    @api.depends("location_log_ids.latitude", "location_log_ids.longitude", "track_latitude", "track_longitude")
    def _compute_tracking_route_url(self):
        import json
        for record in self:
            coords = []
            today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            logs = record.location_log_ids.filtered(lambda l: l.timestamp and l.timestamp >= today_start)
            if not logs:
                logs = record.location_log_ids
            if logs:
                for log in sorted(logs, key=lambda l: l.timestamp or fields.Datetime.now()):
                    if log.latitude or log.longitude:
                        coords.append((log.latitude, log.longitude))
            
            if not coords:
                latest_att = self.env["hr.attendance"].sudo().search([
                    ("employee_id", "=", record.id)
                ], order="check_in desc", limit=1)
                if latest_att and latest_att.location_track_logs:
                    try:
                        data = json.loads(latest_att.location_track_logs)
                        if isinstance(data, list):
                            for item in data:
                                c = item.get("coordinates") if isinstance(item, dict) else item
                                if isinstance(c, (list, tuple)) and len(c) >= 2:
                                    if c[0] or c[1]:
                                        coords.append((c[0], c[1]))
                    except Exception:
                        pass
            
            if not coords and record.track_latitude and record.track_longitude:
                coords.append((record.track_latitude, record.track_longitude))

            record.tracking_route_url = build_google_maps_route_url(coords)

    @api.model
    def get_today_location_logs(self, employee_id):
        employee = self.browse(employee_id)
        if not employee.exists():
            return {
                "status": "error",
                "message": "Employee not found",
                "points": [],
            }
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        logs = employee.location_log_ids.filtered(lambda l: l.timestamp and l.timestamp >= today_start)
        points = []
        for log in sorted(logs, key=lambda l: l.timestamp or fields.Datetime.now()):
            if log.latitude or log.longitude:
                points.append({
                    "latitude": log.latitude,
                    "longitude": log.longitude,
                    "timestamp": fields.Datetime.to_string(log.timestamp),
                })
        return {
            "status": "success",
            "track_latitude": employee.track_latitude,
            "track_longitude": employee.track_longitude,
            "track_last_updated_at": fields.Datetime.to_string(employee.track_last_updated_at) if employee.track_last_updated_at else False,
            "track_map_url": employee.track_map_url,
            "tracking_route_url": employee.tracking_route_url,
            "points": points,
        }

    work_schedule_json = fields.Char("Work Schedule JSON", compute="_compute_work_schedule_json")
    
    def _compute_work_schedule_json(self):
        import json
        for record in self:
            calendar = record.resource_calendar_id
            if not calendar:
                record.work_schedule_json = "{}"
                continue
            
            schedule_data = {
                "tz": calendar.tz or self.env.user.tz or "UTC",
                "hours_per_day": calendar.hours_per_day if hasattr(calendar, 'hours_per_day') else 8.0,
                "attendances": []
            }
            
            for att in calendar.attendance_ids:
                schedule_data["attendances"].append({
                    "dayofweek": int(att.dayofweek),
                    "hour_from": att.hour_from,
                    "hour_to": att.hour_to
                })
                
            record.work_schedule_json = json.dumps(schedule_data)


class HrEmployeeLocationLog(models.Model):
    _name = "hr.employee.location.log"
    _description = "Employee Location Log"
    _order = "timestamp desc, id desc"

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True, ondelete="cascade", index=True)
    latitude = fields.Float("Latitude", digits=(10, 7), required=True)
    longitude = fields.Float("Longitude", digits=(10, 7), required=True)
    timestamp = fields.Datetime("Timestamp", default=fields.Datetime.now, required=True, index=True)
    map_url = fields.Char("Map URL", compute="_compute_map_url")

    @api.depends("latitude", "longitude")
    def _compute_map_url(self):
        for record in self:
            if record.latitude and record.longitude:
                record.map_url = f"https://www.google.com/maps?q={record.latitude},{record.longitude}"
            else:
                record.map_url = False

    @api.model
    def _cron_cleanup_old_location_logs(self):
        """Remove location logs that do not belong to today."""
        today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        old_logs = self.sudo().search([('timestamp', '<', today_start)])
        if old_logs:
            old_logs.unlink()
