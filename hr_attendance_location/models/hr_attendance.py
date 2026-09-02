from odoo import api, fields, models, tools


class HrAttendanceLocation(models.Model):
    _name = "hr.attendance.location"
    _description = "Attendance Map Location"
    _auto = False
    _order = "attendance_datetime desc, id desc"

    attendance_id = fields.Many2one("hr.attendance", string="Attendance", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    location_type = fields.Selection(
        [("check_in", "Check In"), ("check_out", "Check Out")],
        string="Location Type",
        readonly=True,
    )
    attendance_datetime = fields.Datetime(string="Location Time", readonly=True)
    check_in = fields.Datetime(string="Check In", readonly=True)
    check_out = fields.Datetime(string="Check Out", readonly=True)
    latitude = fields.Float(string="Latitude", readonly=True)
    longitude = fields.Float(string="Longitude", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW hr_attendance_location AS (
                SELECT
                    attendance.id * 2 - 1 AS id,
                    attendance.id AS attendance_id,
                    attendance.employee_id AS employee_id,
                    'check_in' AS location_type,
                    attendance.check_in AS attendance_datetime,
                    attendance.check_in AS check_in,
                    attendance.check_out AS check_out,
                    attendance.in_latitude AS latitude,
                    attendance.in_longitude AS longitude,
                    employee.company_id AS company_id
                FROM hr_attendance attendance
                JOIN hr_employee employee ON employee.id = attendance.employee_id
                WHERE NOT (
                    COALESCE(attendance.in_latitude, 0) = 0
                    AND COALESCE(attendance.in_longitude, 0) = 0
                )

                UNION ALL

                SELECT
                    attendance.id * 2 AS id,
                    attendance.id AS attendance_id,
                    attendance.employee_id AS employee_id,
                    'check_out' AS location_type,
                    COALESCE(attendance.check_out, attendance.check_in) AS attendance_datetime,
                    attendance.check_in AS check_in,
                    attendance.check_out AS check_out,
                    attendance.out_latitude AS latitude,
                    attendance.out_longitude AS longitude,
                    employee.company_id AS company_id
                FROM hr_attendance attendance
                JOIN hr_employee employee ON employee.id = attendance.employee_id
                WHERE NOT (
                    COALESCE(attendance.out_latitude, 0) = 0
                    AND COALESCE(attendance.out_longitude, 0) = 0
                )
            )
            """
        )