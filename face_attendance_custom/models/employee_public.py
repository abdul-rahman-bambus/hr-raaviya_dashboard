from odoo import fields, models


class HrEmployeePublicInherit(models.Model):
    _inherit = "hr.employee.public"

    is_enrolled = fields.Boolean(
        related="employee_id.is_enrolled",
        readonly=True,
        compute_sudo=True,
    )
    last_photo_update_time = fields.Datetime(
        related="employee_id.last_photo_update_time",
        readonly=True,
        compute_sudo=True,
    )
    has_employee_tracking = fields.Boolean(
        related="employee_id.has_employee_tracking",
        readonly=True,
        compute_sudo=True,
    )
    track_employee = fields.Boolean(
        related="employee_id.track_employee",
        readonly=True,
        compute_sudo=True,
    )
    track_latitude = fields.Float(
        related="employee_id.track_latitude",
        readonly=True,
        compute_sudo=True,
    )
    track_longitude = fields.Float(
        related="employee_id.track_longitude",
        readonly=True,
        compute_sudo=True,
    )
    track_last_updated_at = fields.Datetime(
        related="employee_id.track_last_updated_at",
        readonly=True,
        compute_sudo=True,
    )
    track_map_url = fields.Char(
        related="employee_id.track_map_url",
        readonly=True,
        compute_sudo=True,
    )
    tracking_route_url = fields.Char(
        related="employee_id.tracking_route_url",
        readonly=True,
        compute_sudo=True,
    )
    work_schedule_json = fields.Char(
        related="employee_id.work_schedule_json",
        readonly=True,
        compute_sudo=True,
    )

