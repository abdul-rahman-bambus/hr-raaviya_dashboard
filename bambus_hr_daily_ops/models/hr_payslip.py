from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    currency_id = fields.Many2one(
        related="company_id.currency_id", readonly=True
    )

    attendance_detail_ids = fields.One2many(
        "bambus.hr.payslip.attendance.detail",
        "payslip_id",
        string="Attendance Earnings and Deductions",
        copy=False,
    )
    attendance_earning_detail_ids = fields.Many2many(
        "bambus.hr.payslip.attendance.detail",
        string="Attendance Earnings",
        compute="_compute_attendance_detail_groups",
    )
    attendance_deduction_detail_ids = fields.Many2many(
        "bambus.hr.payslip.attendance.detail",
        string="Attendance Deductions",
        compute="_compute_attendance_detail_groups",
    )

    @api.depends("attendance_detail_ids.category")
    def _compute_attendance_detail_groups(self):
        for payslip in self:
            payslip.attendance_earning_detail_ids = payslip.attendance_detail_ids.filtered(
                lambda detail: detail.category == "earning"
            )
            payslip.attendance_deduction_detail_ids = payslip.attendance_detail_ids.filtered(
                lambda detail: detail.category == "deduction"
            )

    def action_compute_sheet(self):
        self = self.filtered(lambda slip: slip.state in ('draft', 'verify'))
        result = super().action_compute_sheet()
        self._bambus_rebuild_attendance_details()
        return result

    def _bambus_duration_label(self, hours):
        minutes = max(int(round((hours or 0.0) * 60)), 0)
        if minutes < 60:
            return f"{minutes}m"
        return f"{minutes // 60}h {minutes % 60:02d}m"

    def _bambus_rebuild_attendance_details(self):
        """Snapshot date-wise OT earnings and fine deductions on draft payslips."""
        detail_model = self.env["bambus.hr.payslip.attendance.detail"].sudo()
        attendance_model = self.env["hr.attendance"].sudo()
        sheet_line_model = self.env["bambus.hr.attendance.sheet.line"].sudo()

        for payslip in self:
            payslip.attendance_detail_ids.sudo().unlink()
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                continue

            contract = payslip.contract_id
            tzname = (
                contract.resource_calendar_id.tz
                if contract and contract.resource_calendar_id and contract.resource_calendar_id.tz
                else self.env.user.tz or "UTC"
            )
            timezone = pytz.timezone(tzname)
            start = timezone.localize(datetime.combine(payslip.date_from, time.min))
            end = timezone.localize(
                datetime.combine(payslip.date_to + timedelta(days=1), time.min)
            )
            attendances = attendance_model.search([
                ("employee_id", "=", payslip.employee_id.id),
                ("check_in", ">=", start.astimezone(pytz.UTC).replace(tzinfo=None)),
                ("check_in", "<", end.astimezone(pytz.UTC).replace(tzinfo=None)),
            ], order="check_in, id")
            by_day = defaultdict(lambda: attendance_model.browse())
            for attendance in attendances:
                local_day = fields.Datetime.context_timestamp(
                    self.with_context(tz=tzname), attendance.check_in
                ).date()
                by_day[local_day] |= attendance

            review_lines = sheet_line_model.search([
                ("employee_id", "=", payslip.employee_id.id),
                ("date", ">=", payslip.date_from),
                ("date", "<=", payslip.date_to),
            ])
            review_by_day = {line.date: line for line in review_lines}
            public_holidays = set(payslip._get_public_holiday_dates(
                contract, payslip.date_from, payslip.date_to, tzname
            ))
            values_list = []

            for day, day_attendances in sorted(by_day.items()):
                review = review_by_day.get(day)
                template = payslip.employee_id._get_attendance_automation_template(day)
                last = day_attendances.sorted(
                    key=lambda attendance: (
                        attendance.check_out or attendance.check_in,
                        attendance.id,
                    )
                )[-1]

                overtime_hours = sum(
                    max(attendance.overtime_hours or 0.0, 0.0)
                    for attendance in day_attendances
                )
                overtime_amount = sum(
                    attendance.bambus_overtime_amount or 0.0
                    for attendance in day_attendances
                )
                overtime_state = "detected"
                overtime_type = template.overtime_calculation_type if template else False
                overtime_rate = (
                    overtime_amount / overtime_hours if overtime_hours else 0.0
                )
                if review and review.overtime_state == "approved":
                    overtime_hours = review.overtime_hours or 0.0
                    overtime_amount = review.overtime_amount or 0.0
                    overtime_type = review.overtime_calculation_type
                    overtime_rate = self._bambus_detail_rate(overtime_type, overtime_hours, overtime_amount, review.overtime_rate)
                    overtime_state = "approved"
                elif review and review.overtime_state == "rejected":
                    overtime_hours = 0.0
                    overtime_amount = 0.0
                elif review and review.overtime_state == "submitted":
                    overtime_state = "pending"

                if contract.wage_type == 'hourly':
                    overtime_hours = overtime_amount = 0.0
                elif template and overtime_state != 'approved':
                    overtime_amount = 0.0
                    overtime_state = 'pending'

                if overtime_hours > 0 or overtime_amount > 0:
                    is_public_holiday = day in public_holidays
                    earning_type = (
                        "public_holiday" if is_public_holiday else "overtime"
                    )
                    earning_label = (
                        "Public Holiday" if is_public_holiday else "Overtime"
                    )
                    values_list.append({
                        "payslip_id": payslip.id,
                        "date": day,
                        "category": "earning",
                        "detail_type": earning_type,
                        "hours": overtime_hours,
                        "amount": overtime_amount,
                        "calculation_type": overtime_type,
                        "rate": overtime_rate,
                        "description": "%s %s" % (
                            earning_label,
                            self._bambus_duration_label(
                                overtime_hours
                            ),
                        ),
                        "review_state": overtime_state,
                        "source_line_id": review.id if review else False,
                        "reviewed_by_id": review.overtime_updated_by_id.id if review else False,
                        "reviewed_on": review.overtime_updated_on if review else False,
                    })

                fine_hours = last.bambus_fine_hours or 0.0
                fine_amount = last.bambus_fine_amount or 0.0
                fine_state = "detected"
                fine_type = template.fine_calculation_type if template else False
                fine_rate = fine_amount / fine_hours if fine_hours else 0.0
                if review and review.fine_state == "approved":
                    fine_hours = review.fine_hours or 0.0
                    fine_amount = review.fine_amount or 0.0
                    fine_type = review.fine_calculation_type
                    fine_rate = review.fine_rate or (
                        fine_amount / fine_hours if fine_hours else 0.0
                    )
                    fine_state = "approved"
                elif review and review.fine_state == "rejected":
                    fine_hours = 0.0
                    fine_amount = 0.0
                elif review and review.fine_state == "submitted":
                    fine_state = "pending"

                fine_rate_amount = fine_amount
                if template and fine_state != 'approved':
                    fine_amount = 0.0
                    fine_state = 'pending'

                if fine_hours > 0 or fine_amount > 0:
                    components = []
                    if last.bambus_late_minutes:
                        components.append(
                            "Late Entry %s" % self._bambus_duration_label(
                                last.bambus_late_minutes / 60.0
                            )
                        )
                    if last.bambus_early_leave_minutes:
                        components.append(
                            "Early Exit %s" % self._bambus_duration_label(
                                last.bambus_early_leave_minutes / 60.0
                            )
                        )
                    if last.bambus_gap_minutes:
                        components.append(
                            "Attendance Gap %s" % self._bambus_duration_label(
                                last.bambus_gap_minutes / 60.0
                            )
                        )
                    if review and review.fine_review_data:
                        labels = dict(self.env['bambus.hr.attendance.review.fine']._fields['kind']._description_selection(self.env))
                        components = [
                            "%s %s" % (labels.get(kind, kind), self._bambus_duration_label(value['hours']))
                            for kind, value in review.fine_review_data.items() if value.get('state') == 'approved'
                        ]
                    fine_values = {
                        "payslip_id": payslip.id,
                        "date": day,
                        "category": "deduction",
                        "detail_type": "fine",
                        "hours": fine_hours,
                        "amount": fine_amount,
                        "calculation_type": fine_type,
                        "rate": self._bambus_detail_rate(fine_type, fine_hours, fine_rate_amount, fine_rate),
                        "description": ", ".join(components) or (
                            "Attendance Fine %s" % self._bambus_duration_label(fine_hours)
                        ),
                        "review_state": fine_state,
                        "source_line_id": review.id if review else False,
                        "reviewed_by_id": review.fine_updated_by_id.id if review else False,
                        "reviewed_on": review.fine_updated_on if review else False,
                    }
                    if review and review.fine_review_data and fine_state == 'approved':
                        # A combined approval can contain different methods per
                        # session. Retain those methods/amounts in payroll detail.
                        for kind, decision in review.fine_review_data.items():
                            if decision.get('state') != 'approved':
                                continue
                            hours, amount = decision.get('hours', 0), decision.get('amount', 0)
                            calculation = decision.get('calculation_type', 'fixed')
                            values_list.append(dict(fine_values, hours=hours, amount=amount,
                                calculation_type=calculation,
                                rate=self._bambus_detail_rate(calculation, hours, amount, decision.get('rate', 0)),
                                description='%s %s' % (labels.get(kind, kind), self._bambus_duration_label(hours))))
                    else:
                        values_list.append(fine_values)

            if values_list:
                detail_model.create(values_list)

    @api.model
    def _bambus_detail_rate(self, calculation, hours, amount, stored_rate=0):
        """Explain a saved amount without applying today's wage/template again."""
        if calculation == 'salary_minute':
            return amount / (hours * 60) if hours else 0
        if calculation in ('salary_1', 'salary_1_5', 'salary_2'):
            return amount / hours if hours else 0
        if calculation == 'fixed_hour':
            return amount / hours if hours else stored_rate
        if calculation in ('fixed', 'half_day', 'full_day'):
            return amount
        if calculation == 'regularize':
            return 0
        return stored_rate

    def _bambus_hourly_billable_hours(self, employee, contract, date_from, date_to):
        """Use HR-approved daily payable hours with the effective daily hour cap."""
        billable, attendance_days = super()._bambus_hourly_billable_hours(
            employee, contract, date_from, date_to
        )
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        approved = self.env["bambus.hr.attendance.sheet.line"].sudo().search([
            ("employee_id", "=", employee.id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("hourly_pay_state", "=", "approved"),
        ])
        if not approved:
            return billable, attendance_days

        tzname = (
            contract.resource_calendar_id.tz
            if contract.resource_calendar_id and contract.resource_calendar_id.tz
            else self.env.user.tz or "UTC"
        )
        timezone = pytz.timezone(tzname)
        start = timezone.localize(datetime.combine(date_from, time.min))
        end = timezone.localize(datetime.combine(date_to + timedelta(days=1), time.min))
        attendances = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", start.astimezone(pytz.UTC).replace(tzinfo=None)),
            ("check_in", "<", end.astimezone(pytz.UTC).replace(tzinfo=None)),
        ])
        raw_by_day = defaultdict(float)
        for attendance in attendances:
            local_day = fields.Datetime.context_timestamp(
                self.with_context(tz=tzname), attendance.check_in
            ).date()
            raw_by_day[local_day] += attendance.worked_hours or 0.0

        for line in approved:
            limit = employee._get_attendance_hourly_limit(line.date, contract)
            original = raw_by_day.get(line.date, 0.0)
            original = min(original, limit) if limit > 0 else original
            corrected = max(line.hourly_pay_hours or 0.0, 0.0)
            corrected = min(corrected, limit) if limit > 0 else corrected
            billable += corrected - original
            if corrected and not original:
                attendance_days += 1
            elif original and not corrected:
                attendance_days -= 1
        return max(billable, 0.0), max(attendance_days, 0)


class HrPayslipAttendanceDetail(models.Model):
    _name = "bambus.hr.payslip.attendance.detail"
    _description = "Payslip Attendance Earning or Deduction"
    _order = "date, category, id"

    payslip_id = fields.Many2one(
        "hr.payslip", required=True, ondelete="cascade", index=True
    )
    employee_id = fields.Many2one(
        related="payslip_id.employee_id", store=True, readonly=True
    )
    company_id = fields.Many2one(
        related="payslip_id.company_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", readonly=True
    )
    date = fields.Date(required=True, index=True)
    category = fields.Selection(
        [("earning", "Earning"), ("deduction", "Deduction")],
        required=True,
        index=True,
    )
    detail_type = fields.Selection(
        [
            ("overtime", "Overtime"),
            ("public_holiday", "Public Holiday"),
            ("fine", "Fine"),
        ],
        required=True,
    )
    display_type = fields.Char(
        string="Earning Type", compute="_compute_display_classification"
    )
    hours = fields.Float(string="Duration (Hours)", digits=(16, 6))
    duration_display = fields.Char(
        string="Duration", compute="_compute_duration_display"
    )
    amount = fields.Monetary(currency_field="currency_id")
    calculation_type = fields.Selection([
        ("fixed", "Fixed Amount"),
        ("fixed_hour", "Fixed Amount per Hour"),
        ("half_day", "Half Day"),
        ("full_day", "Full Day"),
        ("regularize", "Regularize"),
        ("salary_minute", "Per Minute from Daily Salary"),
        ("salary_1", "1x Salary"),
        ("salary_1_5", "1.5x Salary"),
        ("salary_2", "2x Salary"),
    ], string="Calculation")
    rate = fields.Float(string="Rate / Amount", digits=(16, 6))
    rate_unit = fields.Char(string="Unit", compute='_compute_rate_unit')

    @api.depends('calculation_type')
    def _compute_rate_unit(self):
        for detail in self:
            detail.rate_unit = ('per minute' if detail.calculation_type == 'salary_minute' else
                                'per hour' if detail.calculation_type in ('fixed_hour', 'salary_1', 'salary_1_5', 'salary_2') else
                                'no charge' if detail.calculation_type == 'regularize' else 'amount')
    description = fields.Char(string="Source Description", required=True)
    display_description = fields.Char(
        string="Description", compute="_compute_display_classification"
    )
    review_state = fields.Selection([
        ("detected", "System Detected"),
        ("pending", "Needs Review"),
        ("approved", "HR Approved"),
    ], required=True, default="detected")
    source_line_id = fields.Many2one(
        "bambus.hr.attendance.sheet.line", string="Attendance Review", readonly=True
    )
    reviewed_by_id = fields.Many2one("res.users", string="Reviewed By", readonly=True)
    reviewed_on = fields.Datetime(string="Reviewed On", readonly=True)

    @api.depends("hours")
    def _compute_duration_display(self):
        for detail in self:
            minutes = max(int(round((detail.hours or 0.0) * 60)), 0)
            detail.duration_display = (
                f"{minutes}m"
                if minutes < 60
                else f"{minutes // 60}h {minutes % 60:02d}m"
            )

    @api.depends(
        "category", "detail_type", "date", "description", "hours",
        "payslip_id.date_from", "payslip_id.date_to", "payslip_id.contract_id",
    )
    def _compute_display_classification(self):
        """Classify old and new snapshots from the actual holiday calendar.

        This keeps existing draft detail rows accurate after a module upgrade,
        even before HR presses Compute Sheet again.
        """
        holiday_dates_by_payslip = {}
        for detail in self:
            payslip = detail.payslip_id
            if payslip not in holiday_dates_by_payslip:
                contract = payslip.contract_id
                tzname = (
                    contract.resource_calendar_id.tz
                    if contract and contract.resource_calendar_id
                    and contract.resource_calendar_id.tz
                    else self.env.user.tz or "UTC"
                )
                holiday_dates_by_payslip[payslip] = set(
                    payslip._get_public_holiday_dates(
                        contract, payslip.date_from, payslip.date_to, tzname
                    )
                ) if payslip.date_from and payslip.date_to else set()

            is_public_holiday = (
                detail.category == "earning"
                and detail.date in holiday_dates_by_payslip[payslip]
            )
            if detail.category == "deduction":
                detail.display_type = "Fine"
            elif is_public_holiday:
                detail.display_type = "Public Holiday"
            else:
                detail.display_type = "Overtime"

            if is_public_holiday:
                detail.display_description = "Public Holiday %s" % (
                    payslip._bambus_duration_label(detail.hours)
                )
            else:
                detail.display_description = detail.description
