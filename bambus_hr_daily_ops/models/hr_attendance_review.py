from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models


REVIEW_STATES = [
    ("draft", "No Exception"),
    ("submitted", "Needs Review"),
    ("approved", "Updated by HR"),
    ("rejected", "Excluded"),
]


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    bambus_review_line_id = fields.Many2one(
        "bambus.hr.attendance.sheet.line",
        string="HR Review",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
    )
    bambus_review_is_daily_summary = fields.Boolean(
        string="Daily Review Row",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
    )
    bambus_overtime_review_state = fields.Selection(
        REVIEW_STATES,
        string="OT Review Status",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
    )
    bambus_fine_review_state = fields.Selection(
        REVIEW_STATES,
        string="Fine Review Status",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
    )
    bambus_approved_overtime_hours = fields.Float(
        string="HR Approved OT",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
        digits=(16, 6),
    )
    bambus_approved_overtime_amount = fields.Monetary(
        string="HR Approved OT Amount",
        currency_field="currency_id",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
    )
    bambus_approved_fine_hours = fields.Float(
        string="HR Approved Fine",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
        digits=(16, 6),
    )
    bambus_approved_fine_amount = fields.Monetary(
        string="HR Approved Fine Amount",
        currency_field="currency_id",
        compute="_compute_bambus_review_values",
        compute_sudo=True,
    )

    @api.depends("employee_id", "check_in", "check_out")
    def _compute_bambus_review_values(self):
        for attendance in self:
            attendance.bambus_review_line_id = False
            attendance.bambus_review_is_daily_summary = False
            attendance.bambus_overtime_review_state = "draft"
            attendance.bambus_fine_review_state = "draft"
            attendance.bambus_approved_overtime_hours = 0.0
            attendance.bambus_approved_overtime_amount = 0.0
            attendance.bambus_approved_fine_hours = 0.0
            attendance.bambus_approved_fine_amount = 0.0

        candidates = self.filtered(lambda item: item.employee_id and item.check_in)
        if not candidates:
            return

        records_by_key = defaultdict(lambda: self.env["hr.attendance"])
        requested_keys = set()
        for attendance in candidates:
            day = attendance._bambus_local_day(attendance.check_in)
            key = (attendance.employee_id.id, day)
            records_by_key[key] |= attendance
            requested_keys.add(key)

        days = [day for _employee_id, day in requested_keys]
        search_start = fields.Datetime.to_datetime(min(days)) - timedelta(days=1)
        search_end = fields.Datetime.to_datetime(max(days)) + timedelta(days=2)
        day_records = self.sudo().search([
            ("employee_id", "in", candidates.employee_id.ids),
            ("check_in", ">=", search_start),
            ("check_in", "<", search_end),
        ])
        for attendance in day_records:
            key = (
                attendance.employee_id.id,
                attendance._bambus_local_day(attendance.check_in),
            )
            if key in requested_keys:
                records_by_key[key] |= attendance

        lines = self.env["bambus.hr.attendance.sheet.line"].sudo().search([
            ("employee_id", "in", candidates.employee_id.ids),
            ("date", ">=", min(days)),
            ("date", "<=", max(days)),
        ])
        line_by_key = {(line.employee_id.id, line.date): line for line in lines}

        for key, records in records_by_key.items():
            line = line_by_key.get(key)
            if not line:
                continue
            last = records.sorted(
                key=lambda item: ((item.check_out or item.check_in), item.id)
            )[-1]
            if last not in self:
                continue
            last.bambus_review_line_id = line
            last.bambus_review_is_daily_summary = True
            last.bambus_overtime_review_state = line.overtime_state or "draft"
            last.bambus_fine_review_state = line.fine_state or "draft"
            if line.overtime_state == "approved":
                last.bambus_approved_overtime_hours = line.overtime_hours
                last.bambus_approved_overtime_amount = line.overtime_amount
            if line.fine_state == "approved":
                last.bambus_approved_fine_hours = line.fine_hours
                last.bambus_approved_fine_amount = line.fine_amount
