from odoo import models, fields, api
from datetime import datetime, timedelta, time
import pytz

class AttendanceReportWizard(models.TransientModel):
    _name = "attendance.report.wizard"
    _description = "Attendance Report Wizard"

    type = fields.Selection([
        ('employee', 'Employee'),
        ('worker', 'Worker')
    ], required=True, default='employee')

    report_type = fields.Selection([
        ('attendance', 'Attendance Report'),
        ('overtime', 'Overtime Report'),
        ('late', 'Fine Report'),
        ('monthly', 'Monthly Summary Report'),
    ], string="Select Report", required=True, default='attendance')

    period = fields.Selection([
        ('current_month', 'Current Month'),
        ('custom', 'Custom Range')
    ], required=True, default='current_month')

    date_start = fields.Date("Start Date")
    date_end = fields.Date("End Date")

    employee_ids = fields.Many2many('hr.employee', string='Employees')

    holidays_filter = fields.Selection([
        ('none', 'None'),
        ('weekend', 'Weekend Days'),
        ('public', 'Public Holidays'),
    ], string="Holidays", default='none')

    weekend_saturday = fields.Boolean("Saturday")
    weekend_sunday = fields.Boolean("Sunday")

    # ---------------- reactive ----------------
    @api.onchange('type')
    def _onchange_type(self):
        if self.type == 'worker':
            self.employee_ids = self.employee_ids.filtered(lambda e: e.employee_type == 'worker')

    @api.onchange('period')
    def _onchange_period(self):
        if self.period == 'current_month':
            user_tz = self.env.user.tz or 'UTC'
            tz = pytz.timezone(user_tz)
            today_utc = datetime.utcnow()
            today_user = pytz.utc.localize(today_utc).astimezone(tz)
            first = today_user.replace(day=1).date()
            next_month = (today_user.replace(day=28) + timedelta(days=4)).replace(day=1)
            last = (next_month - timedelta(days=1)).date()
            self.date_start = first
            self.date_end = last
        else:
            self.date_start = False
            self.date_end = False

    # ---------- employees selection ----------
    def _get_employees(self):
        Employee = self.env['hr.employee']
        Attendance = self.env['hr.attendance']

        if self.employee_ids:
            return self.employee_ids.filtered(lambda e: e.employee_type == self.type)

        if not self.date_start or not self.date_end:
            return Employee.none()

        start_dt = datetime.combine(self.date_start, time.min)
        end_dt = datetime.combine(self.date_end, time.max)

        atts = Attendance.search([
            ('check_in', '>=', fields.Datetime.to_string(start_dt)),
            ('check_in', '<=', fields.Datetime.to_string(end_dt)),
        ])
        return atts.mapped('employee_id').filtered(lambda e: e.employee_type == self.type)


    # ---------- public holidays ----------
    def _get_public_holiday_dates(self):
        if not (self.date_start and self.date_end):
            return set()
        domain = [
            ('date_from', '<=', fields.Datetime.to_string(datetime.combine(self.date_end, time(23,59,59)))),
            ('date_to', '>=', fields.Datetime.to_string(datetime.combine(self.date_start, time(0,0,0)))),
        ]
        leaves = self.env['resource.calendar.leaves'].search(domain)
        dates = set()
        for lv in leaves:
            if lv.date_from and lv.date_to:
                start = fields.Datetime.context_timestamp(self, lv.date_from).date()
                end = fields.Datetime.context_timestamp(self, lv.date_to).date()
                current = start
                while current <= end:
                    dates.add(current)
                    current = current + timedelta(days=1)
        return dates

    # ---------- shift rules: get all shifts for day ----------
    def _get_shift_rules_for_employee_on_date(self, employee, dt_date):
        """
        Return only actual working periods ("Morning", "Afternoon").
        Exclude "Lunch" or any non-working segments.
        """
        contract = employee.contract_id or (employee.contract_ids[:1] if employee.contract_ids else False)
        if not contract:
            return []
        cal = contract.resource_calendar_id
        if not cal:
            return []

        dow = dt_date.weekday()  # Monday = 0

        # Only include working periods (Morning/Afternoon)
        rules = cal.attendance_ids.filtered(
            lambda r:
                r.dayofweek is not None
                and str(int(float(r.dayofweek))) == str(dow)
                and r.day_period and r.day_period.lower() in ('morning', 'afternoon')
        )
        if not rules:
            return []

        shifts = []
        for r in rules:
            hf = float(r.hour_from or 0.0)
            ht = float(r.hour_to or 0.0)
            shifts.append((hf, ht))
        return sorted(shifts, key=lambda x: x[0])

    # ---------- find matching shift start for a check-in ----------
    def _find_matching_shift_start(self, employee, check_in_dt):
        """
        Strict match: compare check-in to shift intervals in LOCAL TZ.
        Always use timezone-aware datetimes to avoid naive/aware errors.
        """
        if not check_in_dt:
            return None

        user_tz = self.env.user.tz or 'UTC'
        tz = pytz.timezone(user_tz)
        ci_local = fields.Datetime.context_timestamp(self, check_in_dt)
        shifts = self._get_shift_rules_for_employee_on_date(employee, ci_local.date())
        if not shifts:
            return None

        for hf, ht in shifts:
            # Shift start (LOCAL TZ)
            h = int(hf)
            m = int(round((hf - h) * 60))
            sh_dt = tz.localize(datetime(ci_local.year, ci_local.month, ci_local.day, h, m, 0))

            # Shift end (LOCAL TZ)
            eh = int(ht)
            em = int(round((ht - eh) * 60))
            end_dt = tz.localize(datetime(ci_local.year, ci_local.month, ci_local.day, eh, em, 0))

            # If the shift end is less than start (overnight), consider end_dt +1 day
            if end_dt <= sh_dt:
                end_dt = end_dt + timedelta(days=1)

            if sh_dt <= ci_local <= end_dt:
                return sh_dt
        return None

    def _get_report_name(self):
        if self.report_type == 'overtime':
            return 'Overtime Report'
        if self.report_type == 'late':
            return 'Fine Report'
        if self.report_type == 'monthly':
            return 'Monthly Summary Report'
        return 'Attendance Report'

    def action_export_xlsx(self):
        return self.env.ref(
            'attendance_custom_report.action_attendance_xlsx'
        ).with_context(
            xlsx_filename=f"{self._get_report_name()}.xlsx"
        ).report_action(self)

    def action_export_pdf(self):
        return self.env.ref('attendance_custom_report.attendance_report_pdf').report_action(self)
