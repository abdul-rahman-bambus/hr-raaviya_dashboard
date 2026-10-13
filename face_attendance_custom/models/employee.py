from odoo import api, models, fields

class HrAEmployeeInherit(models.Model):
    _inherit = "hr.employee"
    
    is_enrolled=fields.Boolean("Is Enrolled")
    last_photo_update_time=fields.Datetime("Last photo update time",default=fields.Datetime.now())
    track_employee = fields.Boolean("Track Employee", default=False)
    
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
