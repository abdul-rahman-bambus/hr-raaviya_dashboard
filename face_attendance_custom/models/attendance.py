import logging

from odoo import api, models, fields

try:
    from geopy.exc import GeocoderServiceError
    from geopy.geocoders import Nominatim
except ImportError:  # pragma: no cover - depends on Odoo env
    GeocoderServiceError = Exception
    Nominatim = None


_logger = logging.getLogger(__name__)

class HrAttendanceInherit(models.Model):
    _inherit = "hr.attendance"
    
    recognized_face_checkin=fields.Image("Recognized Face Check-In",max_width=320,max_height=240)
    recognized_face_checkout=fields.Image("Recognized Face Check-Out",max_width=320,max_height=240)
    attendance_client_id=fields.Char("Attendance client ID")
    checkin_reverse_address = fields.Char(
        "Check-In Address",
        compute="_compute_reverse_addresses",
        store=True,
        readonly=True,
    )
    checkout_reverse_address = fields.Char(
        "Check-Out Address",
        compute="_compute_reverse_addresses",
        store=True,
        readonly=True,
    )

    @api.depends("in_latitude", "in_longitude", "out_latitude", "out_longitude")
    def _compute_reverse_addresses(self):
        for attendance in self:
            attendance.checkin_reverse_address = attendance._reverse_geocode_coordinates(
                attendance.in_latitude,
                attendance.in_longitude,
            )
            attendance.checkout_reverse_address = attendance._reverse_geocode_coordinates(
                attendance.out_latitude,
                attendance.out_longitude,
            )

    @api.model
    def _reverse_geocode_coordinates(self, latitude, longitude):
        if latitude in (False, None) or longitude in (False, None):
            return False
        if not Nominatim:
            return False

        try:
            geolocator = Nominatim(user_agent="face_attendance_custom", timeout=5)
            result = geolocator.reverse(
                (float(latitude), float(longitude)),
                exactly_one=True,
                language="en",
            )
        except (GeocoderServiceError, ValueError):
            _logger.exception(
                "Reverse geocoding failed for attendance coordinates lat=%s lon=%s",
                latitude,
                longitude,
            )
            return False

        if not result:
            return False

        return result.address or False
