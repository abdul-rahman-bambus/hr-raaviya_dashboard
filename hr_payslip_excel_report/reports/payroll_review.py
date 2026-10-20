from collections import defaultdict
from datetime import datetime, time
from types import SimpleNamespace
import io
import zipfile

import pytz
import xlsxwriter

from odoo import _, fields, models
from odoo.exceptions import UserError


# Column kinds: text, number, money, duration (numeric Excel time).
IDENTITY = [('code', 'Employee Code', 'text'), ('name', 'Staff Name', 'text'),
            ('department', 'Department', 'text'), ('staff_type', 'Staff Type', 'text')]
REGISTER = IDENTITY + [
    ('payslip', 'Payslip', 'text'), ('date_from', 'Period From', 'text'), ('date_to', 'Period To', 'text'),
    ('state', 'Payslip Status', 'text'), ('credit', 'Credit Note', 'text'), ('currency', 'Currency', 'text'),
    ('basis', 'Salary Basis', 'text'), ('rate', 'Contract Salary / Rate', 'money'),
    ('payable_days', 'Payable Days (Payslip)', 'number'), ('present', 'Present Day Equivalents', 'number'),
    ('half_days', 'Half-Day Work Occurrences', 'number'), ('paid_leave', 'Paid Leave Days', 'number'),
    ('unpaid_leave', 'Unpaid Leave Days', 'number'), ('absent', 'Absent Working Days', 'number'),
    ('weekly_off', 'Weekly-Off Calendar Days', 'number'), ('weekly_off_worked', 'Weekly-Off Worked Days', 'number'),
    ('holidays', 'Public Holiday Days', 'number'), ('holiday_worked', 'Holiday Worked Days', 'number'),
    ('worked_hours', 'Actual Worked Hours', 'duration'), ('payable_hours', 'Hourly Payable Hours (Payslip)', 'duration'),
    ('ot_hours', 'OT Hours (Payslip)', 'duration'), ('fine_hours', 'Fine Hours (Payslip)', 'duration'),
    ('basic', 'Basic / Hourly Earnings', 'money'), ('overtime', 'Overtime Pay', 'money'),
    ('holiday_pay', 'Holiday / Special-Day Pay', 'money'), ('allowances', 'Other Allowances', 'money'),
    ('earnings', 'Total Earnings', 'money'), ('fine', 'Attendance Fine', 'money'),
    ('advance', 'Advance / Loan Deduction', 'money'), ('other_deductions', 'Other Deductions', 'money'),
    ('deductions', 'Total Deductions', 'money'), ('net', 'Net Pay', 'money'),
    ('pending', 'Pending Review Items', 'number'), ('issues', 'Review Flags', 'text'),
    ('weekly_off_leave', 'Paid Weekly-off Days', 'number'), ('paid_holiday_days', 'Paid Public Holiday Days', 'number'),
]
DAILY = IDENTITY + [
    ('payslip', 'Payslip', 'text'), ('date', 'Date', 'text'), ('classification', 'Day Classification', 'text'),
    ('status', 'Attendance Status', 'text'), ('template', 'Effective Template', 'text'),
    ('source', 'Weekly-Off Source', 'text'), ('policy', 'Weekly-Off Policy', 'text'),
    ('check_in', 'Punch In', 'text'), ('check_out', 'Punch Out', 'text'), ('worked', 'Worked Hours', 'duration'),
    ('ot_detected', 'System OT Hours', 'duration'), ('ot_proposed_amount', 'System OT Amount', 'money'), ('ot_approved', 'HR Approved OT Hours', 'duration'),
    ('ot_amount', 'HR Approved OT Amount', 'money'), ('ot_state', 'OT Review', 'text'),
    ('fine_detected', 'System Fine Hours', 'duration'), ('fine_proposed_amount', 'System Fine Amount', 'money'), ('fine_approved', 'HR Approved Fine Hours', 'duration'),
    ('fine_amount', 'HR Approved Fine Amount', 'money'), ('fine_state', 'Fine Review', 'text'),
    ('hourly_approved', 'HR Updated Hourly Hours', 'duration'), ('hourly_state', 'Hourly Pay Review', 'text'),
    ('saved_ot', 'Payslip Snapshot OT Amount', 'money'), ('saved_fine', 'Payslip Snapshot Fine Amount', 'money'),
    ('reviewed_by', 'Reviewed By', 'text'), ('reviewed_on', 'Reviewed On', 'text'),
    ('paid_weekly_off', 'Normal Weekly-off Day Credit', 'number'),
    ('paid_public_holiday', 'Normal Public Holiday Day Credit', 'number'),
]
EXCEPTIONS = IDENTITY + [('payslip', 'Payslip', 'text'), ('date', 'Date', 'text'),
                         ('issue', 'Review Item', 'text'), ('message', 'Details', 'text')]
SUMMARY = [('staff_type', 'Staff Type', 'text'), ('employees', 'Employees', 'number'),
           ('payslips', 'Payslips', 'number'), ('earnings', 'Total Earnings', 'money'),
           ('deductions', 'Total Deductions', 'money'), ('net', 'Net Pay', 'money'),
           ('pending', 'Pending Review Items', 'number'), ('missing', 'Staff Without Matching Payslip', 'number')]
LEGACY = [('number', 'S.No', 'number'), ('name', 'Staff Name', 'text'),
          ('ctc', 'Total CTC / Contract Salary', 'money'), ('earnings', 'Gross Salary', 'money'),
          ('payable_days', 'Payable Days', 'number'), ('present', 'Present Days', 'number'),
          ('weekly_off_leave', 'Paid Weekly-off Days', 'number'), ('absent', 'Absent Days', 'number'),
          ('holidays', 'Public Holiday Days', 'number'), ('holiday_worked', 'Public Holiday Worked Days', 'number'),
          ('weekly_off_worked', 'Week-off Worked Days', 'number'),
          ('worked_hours', 'Total Work Hours', 'number'), ('ot_hours', 'Overtime Hours', 'number'),
          ('fine_hours', 'Fine Hours', 'number'), ('basic', 'Basic', 'money'),
          ('overtime', 'System Overtime', 'money'), ('public_holiday_pay', 'Public Holiday Pay', 'money'),
          ('earnings', 'Total Earnings', 'money'), ('all_allowances', 'Allowance', 'money'),
          ('fine', 'System Fine', 'money'), ('deductions', 'Total Deductions', 'money'),
          ('net', 'Net Pay Amount', 'money'), ('paid_holiday_days', 'Paid Public Holiday Days', 'number')]



class PayrollReviewReport(models.AbstractModel):
    _name = 'report.hr_payslip_excel_report.payroll_review'
    _description = 'Payroll Review Workbook'

    def _identity(self, employee, contract=None):
        staff_type = contract.contract_type_id.display_name if contract and contract.contract_type_id else dict(
            employee._fields['employee_type']._description_selection(self.env)
        ).get(employee.employee_type, employee.employee_type)
        return {'code': employee.employee_number or '', 'name': employee.name,
                'department': employee.department_id.display_name or '', 'staff_type': staff_type or 'Unclassified'}

    def _category(self, line, code):
        category = line.category_id
        while category:
            if category.code == code:
                return True
            category = category.parent_id
        return False

    def _financials(self, slip):
        if not slip.line_ids:
            return dict.fromkeys(('basic', 'overtime', 'holiday_pay', 'allowances', 'all_allowances',
                                  'earnings', 'fine', 'advance', 'other_deductions', 'deductions', 'net', 'public_holiday_pay'))
        sign = -1 if slip.credit_note else 1
        by_code = defaultdict(float)
        for line in slip.line_ids:
            by_code[line.code] += sign * line.total
        basic = sum(sign * line.total for line in slip.line_ids if self._category(line, 'BASIC'))
        allowances = sum(sign * line.total for line in slip.line_ids if self._category(line, 'ALW'))
        deductions = -sum(sign * line.total for line in slip.line_ids if self._category(line, 'DED'))
        fine = -sum(by_code[code] for code in ('LATE', 'LF'))
        advance = -sum(by_code[code] for code in ('LO', 'SAR'))
        overtime = by_code['OT']
        holiday = by_code['PH'] + by_code['SWD']
        # Missing computed totals are blank, never an invented zero salary.
        codes = set(slip.line_ids.mapped('code'))
        return {'basic': basic if slip.line_ids else None, 'overtime': overtime,
                'holiday_pay': holiday, 'public_holiday_pay': by_code['PH'], 'allowances': allowances - overtime - holiday,
                'all_allowances': allowances, 'earnings': by_code['GROSS'] if 'GROSS' in codes else None,
                'fine': fine, 'advance': advance, 'other_deductions': deductions - fine - advance,
                'deductions': deductions if slip.line_ids else None,
                'net': by_code['NET'] if 'NET' in codes else None}

    def _payable_days(self, slip):
        if not slip.worked_days_line_ids:
            return None
        unpaid_codes = set(self.env['hr.leave.type'].search([('unpaid', '=', True)]).mapped('code')) - {False}
        paid_codes = set(self.env['hr.leave.type'].search([('unpaid', '=', False)]).mapped('code')) - {False}
        ambiguous = paid_codes & unpaid_codes
        if any(line.code in ambiguous for line in slip.worked_days_line_ids):
            return None
        paid_codes |= {'WORK100', 'DAYSWORKED', 'WEEKEND', 'HOLIDAYS', 'PAID_WEEKLY_OFF', 'PAID_PUBLIC_HOLIDAY'}
        # A leave code shared by paid and unpaid types is ambiguous.
        paid_codes -= unpaid_codes
        if any(line.code not in paid_codes | unpaid_codes for line in slip.worked_days_line_ids):
            return None
        return sum(line.number_of_days for line in slip.worked_days_line_ids if line.code in paid_codes)

    def _resolve_duplicate_periods(self, slips):
        """Choose one regular slip per employee/contract/period; retain refunds."""
        groups = defaultdict(list)
        selected = self.env['hr.payslip']
        excluded = []
        for slip in slips:
            if slip.credit_note:
                selected |= slip
            else:
                groups[(slip.employee_id.id, slip.contract_id.id, slip.date_from, slip.date_to)].append(slip)
        state_rank = {'done': 3, 'verify': 2, 'draft': 1, 'cancel': 0}
        for candidates in groups.values():
            def rank(slip):
                codes = set(slip.line_ids.mapped('code'))
                return (state_rank.get(slip.state, 0), {'GROSS', 'NET'} <= codes,
                        slip.write_date or slip.create_date, slip.id)
            winner = max(candidates, key=rank)
            selected |= winner
            excluded.extend((slip, winner) for slip in candidates if slip != winner)
        return selected.sorted(key=lambda slip: (slip.employee_id.name or '', slip.date_from, slip.id)), excluded

    def _employee_summary_rows(self, rows):
        """Salary sums include refunds; repeated attendance periods count once."""
        grouped = defaultdict(list)
        for row in rows:
            grouped[row['employee_id']].append(row)
        output = []
        salary_keys = ('basic', 'all_allowances', 'earnings', 'deductions', 'net', 'overtime', 'fine', 'public_holiday_pay')
        attendance_keys = ('payable_days', 'present', 'weekly_off_leave', 'paid_holiday_days', 'absent', 'holidays', 'weekly_off_worked', 'holiday_worked',
                           'worked_hours', 'ot_hours', 'fine_hours')
        for employee_rows in grouped.values():
            merged = dict(employee_rows[0])
            for key in salary_keys:
                values = [row.get(key) for row in employee_rows]
                merged[key] = sum(values) if all(value is not None for value in values) else None
            periods = {}
            for row in employee_rows:
                if row['credit'] == 'No':
                    periods.setdefault((row['date_from'], row['date_to']), row)
            periods = list(periods.values())
            overlaps = any(left['date_from'] <= right['date_to'] and right['date_from'] <= left['date_to']
                           for i, left in enumerate(periods) for right in periods[i + 1:])
            for key in attendance_keys:
                values = [row.get(key) for row in periods]
                merged[key] = sum(values) if periods and not overlaps and all(value is not None for value in values) else None
            monthly_salaries = {row.get('ctc') for row in periods}
            merged['ctc'] = next(iter(monthly_salaries)) if len(monthly_salaries) == 1 else None
            contract_rates = {row.get('rate') for row in employee_rows}
            merged['rate'] = next(iter(contract_rates)) if len(contract_rates) == 1 else None
            merged['issues'] = '; '.join(dict.fromkeys(row['issues'] for row in employee_rows if row.get('issues')))
            if len(contract_rates) > 1:
                merged['issues'] = '; '.join(filter(None, (merged['issues'], 'Multiple contract rates; see Payroll Review')))
            output.append(merged)
        return output

    def _salary_type_rows(self, rows):
        groups = {'monthly': [], 'hourly': [], 'daily': []}
        for row in rows:
            wage_type = row.get('wage_type')
            if wage_type not in groups:
                raise UserError(_('Payslip %s has no Monthly, Hourly, or Daily salary type on its contract. '
                                  'Correct the contract or use Payroll Review to inspect it.') % row['payslip'])
            groups[wage_type].append(row)
        return {wage_type: self._employee_summary_rows(items) for wage_type, items in groups.items()}

    def _write_salary_summary(self, workbook, data, wizard):
        groups = self._salary_type_rows(data['register'])
        final_columns = [('salary_type', 'Salary Type', 'text'), ('employees', 'Employees', 'number'),
                         ('contract_value', 'Contract Salary / Rate Total', 'money')] + LEGACY[3:]
        final_rows, source_refs = [], []
        for wage_type, name in (('monthly', 'Monthly'), ('hourly', 'Hourly'), ('daily', 'Daily')):
            rows = [dict(row, number=index) for index, row in enumerate(groups[wage_type], 1)]
            columns = list(LEGACY)
            if wage_type == 'hourly':
                columns[2] = ('rate', 'Hourly Rate (per Hour)', 'money')
            elif wage_type == 'daily':
                columns[2] = ('rate', 'Daily Wage (per Day)', 'money')
            sheet = self._write_sheet(workbook, name, columns, rows, wizard, totals=True,
                                      include_ctc=True, include_rates=True, empty_totals=True, decimal_hours=True)
            sheet.write_comment(5, 2, 'Monthly salary uses contract.wage; hourly uses hourly_rate; daily uses daily_wage. '
                                    'Totals sum configured salaries/rates, not earned pay. Varying rates remain blank; see Payroll Review.')
            sheet.write_comment(5, 6, 'Normal weekly-off credits, including worked dates. Approved work is paid separately; no leave balance is created.')
            sheet.write_string(4, 0, f"Salary type: {name}. Duplicate payslips excluded: {data['excluded_count']}. Selection details are in Payroll Review.")
            final = {'salary_type': name, 'employees': len(rows)}
            for column, (key, label, kind) in enumerate(columns[2:], 2):
                values = [row[key] for row in rows if row.get(key) is not None]
                final['contract_value' if column == 2 else key] = sum(values) if values else (None if rows else 0)
            final_rows.append(final)
            # Excel row of the type sheet's SUBTOTAL footer.
            source_refs.append((name, max(7, 6 + len(rows)), 8 + len(rows)))
        sheet = self._write_sheet(workbook, 'Final Summary', final_columns, final_rows,
                                  wizard, decimal_hours=True)
        sheet.write_string(3, 0, 'Three salary-type totals. Formulas follow filters on the detail sheets; only available values are summed.')
        sheet.write_string(4, 0, 'Contract column: monthly salary, hourly rate, or daily wage by row. Rate totals are not earned pay.')
        sheet.write_comment(5, 2, 'Monthly totals are monthly contract salaries. Hourly/daily totals are sums of configured per-hour/per-day rates. Gross and Net columns show actual payslip amounts.')
        number_format = workbook.add_format({'num_format': '0.##'})
        money_format = workbook.add_format({'num_format': '#,##0.00;[Red]-#,##0.00'})
        for index, (row, (name, last, footer)) in enumerate(zip(final_rows, source_refs), 6):
            sheet.write_formula(index, 1, f"=SUBTOTAL(103,'{name}'!B7:B{last})", number_format, row['employees'])
            for column, (key, label, kind) in enumerate(final_columns[2:], 2):
                if row[key] is not None:
                    letter = xlsxwriter.utility.xl_col_to_name(column)
                    sheet.write_formula(index, column, f"='{name}'!{letter}{footer}",
                                        money_format if kind == 'money' else number_format, row[key])

    def _data(self, wizard):
        slips, excluded = self._resolve_duplicate_periods(wizard._selected_payslips())
        if wizard.report_type == 'summary' and not slips:
            raise UserError(_('No payslips match the selected period and filters.'))
        employees = wizard._scope_employees() | slips.employee_id
        if not employees:
            raise UserError(_('No employees match the selected filters.'))
        register, daily_rows, exceptions = [], [], []
        groups = defaultdict(lambda: {'employees': set(), 'payslips': 0, 'earnings': 0.,
                                      'deductions': 0., 'net': 0., 'pending': 0, 'missing': 0})
        day_cache = {}
        attendance_report = self.env['report.attendance_custom_report.attendance_xlsx']

        def issue(base, kind, message, day=None):
            exceptions.append({**base, 'date': str(day or ''), 'issue': kind, 'message': message})

        for skipped, winner in excluded:
            issue({**self._identity(skipped.employee_id, skipped.contract_id),
                   'payslip': skipped.number or skipped.name or str(skipped.id)},
                  'Duplicate Payslip Excluded',
                  f'ID {skipped.id} excluded; ID {winner.id} selected for {winner.date_from} to {winner.date_to}. '
                  'Selection: Done, Waiting, Draft; then computed totals; then latest update and ID.')

        for employee in employees.sorted('name'):
            employee_slips = slips.filtered(lambda slip: slip.employee_id == employee)
            if not employee_slips:
                base = self._identity(employee, employee.contract_id)
                group = groups[base['staff_type']]
                group['employees'].add(employee.id)
                group['missing'] += 1
                if wizard.report_type == 'review':
                    issue(base, 'No Matching Payslip', 'No payslip matches the selected period and status.')
                    register.append({**base, 'state': 'No Matching Payslip', 'currency': wizard.company_id.currency_id.name,
                                     'issues': 'No matching payslip', 'pending': 0})
                continue
            for slip in employee_slips:
                base = {**self._identity(employee, slip.contract_id), 'payslip': slip.number or slip.name or str(slip.id)}
                flags = []
                finance = self._financials(slip)
                contract = slip.contract_id
                payable_days = self._payable_days(slip)
                overlaps = employee_slips.filtered(lambda other: other != slip and not other.credit_note
                    and not slip.credit_note and other.date_from <= slip.date_to and other.date_to >= slip.date_from)
                if overlaps:
                    flags.append('Overlapping payslips')
                    issue(base, 'Overlapping Payslips', 'Every selected payslip is included in totals; review: ' + ', '.join(overlaps.mapped('display_name')))
                if not contract:
                    flags.append('Missing contract')
                    issue(base, 'Missing Contract', 'The payslip has no contract.')
                if finance['earnings'] is None or finance['net'] is None:
                    flags.append('Missing computed salary totals')
                    issue(base, 'Uncomputed Payslip', 'GROSS or NET salary lines are missing. Amounts remain blank.')
                elif not slip.company_id.currency_id.is_zero(finance['earnings'] - finance['deductions'] - finance['net']):
                    flags.append('Salary reconciliation mismatch')
                    issue(base, 'Salary Reconciliation', 'Payslip GROSS less deductions does not equal NET. Check salary rules.')
                if payable_days is None:
                    flags.append('Payable days unavailable')
                    issue(base, 'Payable Days', 'Worked-day buckets are missing or have unmapped leave codes; payable days are left blank.')
                row = {**base, **finance, 'employee_id': employee.id, 'date_from': str(slip.date_from), 'date_to': str(slip.date_to),
                       'state': dict(slip._fields['state']._description_selection(self.env)).get(slip.state, slip.state),
                       'wage_type': contract.wage_type if contract else False,
                       'credit': 'Yes' if slip.credit_note else 'No', 'currency': slip.company_id.currency_id.name,
                       'basis': dict(contract._fields['wage_type']._description_selection(self.env)).get(contract.wage_type, '') if contract else '',
                       'ctc': contract.wage if contract and contract.wage_type == 'monthly' else None,
                       'rate': (contract.hourly_rate if contract.wage_type == 'hourly' else contract.daily_wage if contract.wage_type == 'daily' else contract.wage) if contract else None,
                       'payable_days': payable_days, 'present': slip.total_working_days + slip.weekend_worked + slip.holiday_worked,
                       'weekly_off_worked': slip.weekend_worked, 'holiday_worked': slip.holiday_worked,
                       'payable_hours': slip.total_worker_hours if contract and contract.wage_type == 'hourly' else None,
                       'ot_hours': slip.total_validated_overtime, 'fine_hours': slip.total_fine_hours, 'pending': 0}
                key = (employee.id, slip.date_from, slip.date_to, contract.id)
                if key not in day_cache:
                    day_cache[key] = attendance_report._compute_employee_daily(employee,
                        SimpleNamespace(date_start=slip.date_from, date_end=slip.date_to), contract=contract)
                daily, counts = self._daily_data(slip, base, day_cache[key], issue)
                if wizard.report_type == 'review':
                    daily_rows.extend(daily)
                row.update(counts)
                if row['pending']:
                    flags.append('Pending attendance reviews')
                row['issues'] = '; '.join(flags)
                register.append(row)
                group = groups[base['staff_type']]
                group['employees'].add(employee.id)
                group['payslips'] += 1
                for field in ('earnings', 'deductions', 'net', 'pending'):
                    group[field] += row.get(field) or 0
        summary = [{**group, 'staff_type': staff_type, 'employees': len(group['employees'])}
                   for staff_type, group in sorted(groups.items())]
        return {'register': register, 'daily': daily_rows, 'exceptions': exceptions, 'summary': summary,
                'employee_count': len(employees), 'excluded_count': len(excluded)}

    def _daily_data(self, slip, base, daily, issue):
        employee = slip.employee_id
        tzname = self.env['report.attendance_custom_report.attendance_xlsx']._get_emp_tzname(employee, slip.contract_id)
        reviews = self.env['bambus.hr.attendance.sheet.line'].search([
            ('employee_id', '=', employee.id), ('company_id', '=', slip.company_id.id),
            ('date', '>=', slip.date_from), ('date', '<=', slip.date_to)])
        reviews = {review.date: review for review in reviews}
        timezone = pytz.timezone(tzname)
        utc_start = timezone.localize(datetime.combine(slip.date_from, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = timezone.localize(datetime.combine(slip.date_to, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
        leaves = self.env['hr.leave'].search([('employee_id', '=', employee.id), ('state', '=', 'validate'),
                                            ('date_from', '<=', utc_end), ('date_to', '>=', utc_start)])
        counts = dict.fromkeys(('present', 'half_days', 'paid_leave', 'unpaid_leave', 'absent',
                               'weekly_off', 'weekly_off_leave', 'paid_holiday_days', 'weekly_off_worked', 'holidays', 'holiday_worked', 'worked_hours', 'pending'), 0)
        rows = []
        for day, info in sorted(daily.items()):
            template = employee._get_attendance_automation_template(day)
            review = reviews.get(day)
            attendance = info['attendances']
            day_leaves = leaves.filtered(lambda leave: fields.Datetime.context_timestamp(self.with_context(tz=tzname), leave.date_from).date()
                <= day <= fields.Datetime.context_timestamp(self.with_context(tz=tzname), leave.date_to).date())
            work_periods = employee._get_attendance_work_periods(day)
            day_leave = day_leaves[:1] if work_periods and not info['is_weekend'] and not info['is_holiday'] else self.env['hr.leave']
            paid = unpaid = 0.
            if day_leave:
                fraction = .5 if day_leave.request_unit_half else 1.
                if day_leave.request_unit_hours:
                    scheduled = sum(end - start for start, end in work_periods)
                    fraction = min(1., max(0., (day_leave.request_hour_to - day_leave.request_hour_from) / scheduled)) if scheduled else 0.
                if day_leave.holiday_status_id.unpaid:
                    unpaid = fraction
                else:
                    paid = fraction
            fraction = info['day_fraction']
            if review and review.attendance_status_manual:
                fraction = {'present': 1., 'halfday': .5, 'absent': 0., 'leave': 0.}.get(review.status, fraction)
            if day_leave:
                fraction = min(fraction, 1 - paid - unpaid)
            status = 'Present' if fraction >= 1 else 'Half Day' if fraction == .5 else 'Absent' if info['is_absent'] else 'No Attendance'
            paid_weekly_off = (info['is_weekend']
                and employee._is_paid_attendance_weekly_off(day, slip.contract_id))
            paid_holiday = (info['is_holiday']
                and employee._is_paid_attendance_public_holiday(day, slip.contract_id))
            if paid_weekly_off:
                status = 'Worked Paid Weekly Off' if attendance else 'Paid Weekly Off'
            elif paid_holiday:
                status = 'Worked Paid Public Holiday' if attendance else 'Paid Public Holiday'
            if day_leave:
                status = 'Half-Day Leave' if day_leave.request_unit_half else 'Unpaid Leave' if unpaid else 'Paid Leave'
            classification = 'Public Holiday' if info['is_holiday'] else 'Weekly Off' if info['is_weekend'] else 'Working Day'
            counts['present'] += fraction
            counts['half_days'] += fraction == .5
            counts['paid_leave'] += paid
            counts['unpaid_leave'] += unpaid
            counts['absent'] += max(0., 1 - fraction - paid - unpaid) if work_periods and not info['is_weekend'] and not info['is_holiday'] else 0
            counts['weekly_off_leave'] += 1 if paid_weekly_off else 0
            counts['paid_holiday_days'] += 1 if paid_holiday else 0
            counts['weekly_off'] += info['is_weekend']
            counts['weekly_off_worked'] += fraction if info['is_weekend'] else 0
            counts['holidays'] += info['is_holiday']
            counts['holiday_worked'] += fraction if info['is_holiday'] else 0
            counts['worked_hours'] += info['worked']
            last = self.env['report.attendance_custom_report.attendance_xlsx']._last_attendance(attendance)
            snapshot = slip.attendance_detail_ids.filtered(lambda detail: detail.date == day)
            row = {**base, 'date': str(day), 'classification': classification, 'status': status,
                   'paid_weekly_off': int(paid_weekly_off), 'paid_public_holiday': int(paid_holiday),
                   'template': template.name if template else 'Assigned schedule / legacy fallback',
                   'source': dict(template._fields['weekly_off_source']._description_selection(self.env)).get(template.weekly_off_source, '') if template else 'Assigned Working Schedule',
                   'policy': dict(template._fields['weekly_off_overtime_policy']._description_selection(self.env)).get(template.weekly_off_overtime_policy, '') if template else '',
                   'check_in': '; '.join(fields.Datetime.context_timestamp(self.with_context(tz=tzname), att.check_in).strftime('%H:%M') for att in attendance),
                   'check_out': '; '.join(fields.Datetime.context_timestamp(self.with_context(tz=tzname), att.check_out).strftime('%H:%M') if att.check_out else 'Missing' for att in attendance),
                   'worked': info['worked'], 'ot_detected': sum(max(att.overtime_hours, 0) for att in attendance),
                   'ot_proposed_amount': sum(attendance.mapped('bambus_overtime_amount')),
                   'fine_detected': last.bambus_fine_hours if last else 0,
                   'fine_proposed_amount': last.bambus_fine_amount if last else 0,
                   'saved_ot': sum(snapshot.filtered(lambda detail: detail.category == 'earning').mapped('amount')),
                   'saved_fine': sum(snapshot.filtered(lambda detail: detail.category == 'deduction').mapped('amount'))}
            reviewers, reviewed_times = [], []
            for kind in ('overtime', 'fine', 'hourly_pay'):
                short = {'overtime': 'ot', 'fine': 'fine', 'hourly_pay': 'hourly'}[kind]
                state = review[f'{kind}_state'] if review else 'draft'
                row[f'{short}_state'] = {'draft': 'System / Not Reviewed', 'submitted': 'Needs Review',
                                        'approved': 'HR Approved', 'rejected': 'Excluded'}.get(state, state)
                if state == 'approved':
                    row[f'{short}_approved'] = review[f'{kind}_hours']
                    row[f'{short}_amount'] = review[f'{kind}_amount']
                    user = review[f'{kind}_updated_by_id']
                    when = review[f'{kind}_updated_on']
                    if user:
                        reviewers.append(user.display_name)
                    if when:
                        reviewed_times.append(str(fields.Datetime.context_timestamp(self.with_context(tz=tzname), when)))
                if state == 'submitted':
                    counts['pending'] += 1
                    issue(base, 'Pending ' + kind.replace('_', ' ').title(), 'HR review is needed; payroll amounts are unchanged by this export.', day)
            row['reviewed_by'] = '; '.join(dict.fromkeys(reviewers))
            row['reviewed_on'] = '; '.join(dict.fromkeys(reviewed_times))
            if any(not att.check_out for att in attendance):
                issue(base, 'Missing Punch Out', 'Complete the attendance before final payroll review.', day)
            if not template and (attendance or employee._get_attendance_work_periods(day)):
                issue(base, 'No Effective Template', 'Assigned schedule and legacy fallback rules apply on this date.', day)
            for kind, category in (('overtime', 'earning'), ('fine', 'deduction')):
                saved = snapshot.filtered(lambda detail: detail.category == category)
                if review and review[f'{kind}_state'] == 'approved' and ((not saved and review[f'{kind}_amount']) or
                    not slip.company_id.currency_id.is_zero(sum(saved.mapped('amount')) - review[f'{kind}_amount'])):
                    issue(base, 'Payslip Snapshot Differs from HR Review',
                          'The current approved ' + kind + ' differs from the saved payslip detail; review a draft recomputation.', day)
            for detail in snapshot:
                if detail.review_state == 'pending' and (not review or review[f'{"fine" if detail.detail_type == "fine" else "overtime"}_state'] != 'submitted'):
                    counts['pending'] += 1
                    issue(base, 'Payslip Snapshot Needs Review', 'The saved payslip detail still needs review; consider recomputing a draft payslip.', day)
            rows.append(row)
        return rows, counts

    def _write_sheet(self, workbook, name, columns, rows, wizard, totals=False, employee_count=None,
                     include_ctc=False, include_rates=False, empty_totals=False, decimal_hours=False):
        sheet = workbook.add_worksheet(name)
        title = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#233B53'})
        header = workbook.add_format({'bold': True, 'bg_color': '#DDEBF7', 'border': 1, 'text_wrap': True})
        formats = {'text': workbook.add_format({'valign': 'top'}),
                   'number': workbook.add_format({'num_format': '0.##'}),
                   'money': workbook.add_format({'num_format': '#,##0.00;[Red]-#,##0.00'}),
                   'duration': workbook.add_format({'num_format': '[h]:mm'})}
        warning = workbook.add_format({'bg_color': '#FFF2CC'})
        start, end = wizard._period_dates()
        sheet.write_string(0, 0, name, title)
        status_label = dict(wizard._fields['payslip_status']._description_selection(self.env))[wizard.payslip_status]
        sheet.write_string(1, 0, f'{wizard.company_id.name} | {start} to {end} | {wizard.company_id.currency_id.name} | Status: {status_label}' + (f' | Batch: {wizard.batch_id.name}' if wizard.batch_id else ''))
        units = 'Hours: decimal hours.' if decimal_hours else 'Durations: HH:MM.'
        sheet.write_string(2, 0, 'Salary: saved payslip lines. Attendance/reviews: current records. ' + units + ' Blank values: unavailable.')
        sheet.write_string(3, 0, 'Summary: one row per employee. Exact duplicate payslips are resolved; Payroll Review lists exclusions. Overlapping periods need review.')
        for col, (key, label, kind) in enumerate(columns):
            sheet.write_string(5, col, label, header)
            sheet.set_column(col, col, 25 if kind == 'text' else 18, formats[kind])
        sheet.set_row(5, 42)
        for index, row in enumerate(rows, 6):
            for col, (key, label, kind) in enumerate(columns):
                value = row.get(key)
                if value is None:
                    sheet.write_blank(index, col, None, formats[kind])
                elif kind == 'text':
                    # Never interpret staff names/notes beginning with '=' as formulas.
                    sheet.write_string(index, col, str(value), formats[kind])
                else:
                    sheet.write_number(index, col, value / 24 if kind == 'duration' else value, formats[kind])
            if row.get('issues') or row.get('pending') or row.get('issue'):
                sheet.conditional_format(index, 0, index, len(columns) - 1,
                                         {'type': 'formula', 'criteria': '=TRUE', 'format': warning})
        last = 5 + len(rows)
        sheet.autofilter(5, 0, max(5, last), len(columns) - 1)
        if totals and (rows or empty_totals):
            for col, (key, label, kind) in enumerate(columns):
                if kind in ('money', 'number', 'duration') and key != 'number' and (key != 'rate' or include_rates) and (key != 'ctc' or include_ctc):
                    # SUBTOTAL respects Excel filters; cache values for readers without Excel.
                    values = [row[key] for row in rows if row.get(key) is not None]
                    if values or not rows:
                        letter = xlsxwriter.utility.xl_col_to_name(col)
                        total = sum(values) / (24 if kind == 'duration' else 1)
                        if key == 'employees' and employee_count is not None:
                            sheet.write_number(last + 2, col, employee_count, formats[kind])
                            continue
                        sheet.write_formula(last + 2, col, f'=SUBTOTAL(109,{letter}7:{letter}{max(7, last+1)})', formats[kind], total)
            sheet.write_string(last + 2, 0, 'Filtered Totals', header)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(5)
        return sheet

    def _generate(self, wizard):
        data = self._data(wizard)
        output = io.BytesIO()
        with xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False}) as workbook:
            workbook.set_properties({'title': 'Payroll Review', 'company': wizard.company_id.name})
            if wizard.report_type == 'review':
                self._write_sheet(workbook, 'Payroll Summary', SUMMARY, data['summary'], wizard, totals=True, employee_count=data['employee_count'])
                self._write_sheet(workbook, 'Employee Payroll Register', REGISTER, data['register'], wizard, totals=True)
                self._write_sheet(workbook, 'Attendance & Adjustments', DAILY, data['daily'], wizard)
                self._write_sheet(workbook, 'Review Exceptions', EXCEPTIONS, data['exceptions'], wizard)
            else:
                self._write_salary_summary(workbook, data, wizard)
        # Workbook-level scrollbars are a supported Excel view preference.
        # Keep all cells available; spreadsheet applications may override it.
        result = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(output.getvalue())) as source, zipfile.ZipFile(result, 'w') as target:
            for entry in source.infolist():
                content = source.read(entry.filename)
                if entry.filename == 'xl/workbook.xml':
                    content = content.replace(b'<workbookView ',
                        b'<workbookView showHorizontalScroll="0" showVerticalScroll="0" ', 1)
                target.writestr(entry, content)
        return result.getvalue()
