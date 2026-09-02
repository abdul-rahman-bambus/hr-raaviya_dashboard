from odoo import http, _
from odoo.http import content_disposition, request
import io
import xlsxwriter
from datetime import datetime
import calendar

class ExcelReportController(http.Controller):
    
    
    # -------------------------------------------
    # FIND ATTENDANCE RECORDS FOR PERIOD
    # -------------------------------------------
    def _attendance_in_range(self, emp_id, dfrom, dto):
        """Return hr.attendance entries whose check_in lies inside [dfrom, dto]."""
        dfrom = datetime(dfrom.year, dfrom.month, dfrom.day, 0, 0, 0)
        dto   = datetime(dto.year, dto.month, dto.day, 23, 59, 59)

        return request.env['hr.attendance'].search([
            ('employee_id', '=', emp_id),
            ('check_in', '>=', dfrom),
            ('check_in', '<=', dto),
        ])
        
    # -------------------------------------------
    # CONVERT FLOAT DURATION TO HH:MM
    # -------------------------------------------
    def convert_to_hours_minutes(self, duration):
        if duration:
            hours = int(duration)
            minutes = int(round((duration - hours) * 60))
            duration = f"{hours:02d}:{minutes:02d}"
        return duration

    @http.route('/my_excel/download', type='http', auth='user')
    def download_excel(self, **kwargs):

        # Create an in-memory output file for the new workbook.
        output = io.BytesIO()

        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet("Report")

        header = ["S.No", "Staff Name", "Payable Days", "Present Days", 
                  "Weekend Working Days", "Holiday Working Days", "Total Work Hours", "Overtime Hours", "Fine Hours",
                  "Basic", "Allowance", "Gross Salary", "Total Deduction", "Net Pay Amount"]

        payslips = request.env["hr.payslip"].search([])
        employees = payslips.mapped('employee_id') if payslips else False
        current_url = request.httprequest.url
        wizard_id = 0
        if current_url and "id=" in current_url:
            wizard_id = current_url.split("id=")[1]
        wizard = request.env["payslip.excel.wizard"].browse(int(wizard_id))
        duration_type = wizard.duration_type
        start_date = wizard.start_date
        end_date = wizard.end_date
        if duration_type == 'current':
            start_date = datetime(datetime.today().year, datetime.today().month, 1, 0, 0, 0)
            last_day = calendar.monthrange(datetime.today().year, datetime.today().month)[1]
            end_date = datetime(datetime.today().year, datetime.today().month, last_day, 0, 0, 0)
        
        bold = workbook.add_format({'bold': True})
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#DDEBF7',
            'border': 1,
            'align': 'center',
        })
        cell_format = workbook.add_format({
            'align': 'center',
        })

        # Write sample data
        for head in range(len(header)):
            sheet.set_column(0, head, len(header[head]) + 4)
            sheet.write(0, head, header[head], header_format)
        
        line = 1
        for employee in sorted(list(set(employees)), key=lambda x: x["name"]):
            attendances = self._attendance_in_range(employee.id, start_date, end_date)
            payslip = payslips.filtered(lambda l: l.employee_id.id == employee.id and l.date_from == start_date and l.date_to == end_date) or False
            if not payslip:
                continue
            if payslip and len(payslip) > 1:
                payslip = payslip[0]
            gross_pay_line = payslip.line_ids.filtered(lambda l: l.code == "GROSS") if payslip else False
            basic_pay_line = payslip.line_ids.filtered(lambda l: l.code == "BASIC") if payslip else False
            net_pay_line = payslip.line_ids.filtered(lambda l: l.code == "NET") if payslip else False
            allowance_lines = payslip.line_ids.filtered(lambda l: l.category_id.id == request.env.ref('hr_payroll_community.ALW').id) if payslip else False
            deduction_lines = payslip.line_ids.filtered(lambda l: l.category_id.id == request.env.ref('hr_payroll_community.DED').id) if payslip else False
            gross_pay = gross_pay_line.total if gross_pay_line else 0
            basic_pay = basic_pay_line.total if basic_pay_line else 0
            net_pay = net_pay_line.total if net_pay_line else 0
            allowance_total = sum(allowance_lines.mapped("total")) if allowance_lines else 0
            deduction_total = sum(deduction_lines.mapped("total")) if deduction_lines else 0
            total_working_days = payslip.days_excl_weekend_holidays + payslip.holiday_days + payslip.weekend_days
            if not attendances:
                continue
            total_days = []
            sundays = []
            worked_hours = []
            for att in attendances:
                if att.check_in.date() not in total_days:
                    total_days.append(att.check_in.date())
                    if att.check_in.date().weekday() == "6":
                        sundays.append(att.check_in.date())
                    worked_hours.append(att.worked_hours)
            
            sheet.write(line, 0, line, cell_format)
            sheet.write(line, 1, employee.name, cell_format)
            sheet.write(line, 2, total_working_days, cell_format)
            sheet.write(line, 3, payslip.days_excl_weekend_holidays, cell_format)
            sheet.write(line, 4, payslip.weekend_days, cell_format)
            sheet.write(line, 5, payslip.holiday_days, cell_format)
            sheet.write(line, 6, self.convert_to_hours_minutes(payslip.total_worked_hours_excl_ot), cell_format)
            sheet.write(line, 7, self.convert_to_hours_minutes(payslip.total_validated_overtime) or 0, cell_format)
            sheet.write(line, 8, self.convert_to_hours_minutes(payslip.total_late_login_minutes) or 0, cell_format)
            sheet.write(line, 9, basic_pay or 0, cell_format)
            sheet.write(line, 10, allowance_total or 0, cell_format)
            sheet.write(line, 11, gross_pay, cell_format)
            sheet.write(line, 12, -(deduction_total) or 0, cell_format)
            sheet.write(line, 13, net_pay or 0, cell_format)

            line += 1

        workbook.close()
        output.seek(0)

        # Return as attachment
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition('payslip_excel_report.xlsx'))
            ]
        )


