from odoo import fields, models


class HrAttendanceInherit(models.Model):
    _inherit = "hr.attendance"
    
    recognized_face_checkin=fields.Image("Recognized Face Check-In",max_width=320,max_height=240)
    recognized_face_checkout=fields.Image("Recognized Face Check-Out",max_width=320,max_height=240)
    attendance_client_id=fields.Char("Attendance client ID")
    checkin_address = fields.Char("Check-In Address")
    checkout_address = fields.Char("Check-Out Address")

    expected_checkout_time = fields.Datetime("Expected Checkout Time", compute="_compute_expected_checkout_time")

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
