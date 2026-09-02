
{
    "name": "Attendance Custom Report",
    "version": "1.0",
    "category": "Human Resources",
    "depends": ["hr", "hr_attendance", "report_xlsx", "custom_hr_payroll"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/attendance_report_wizard_view.xml",
        "reports/attendance_report_pdf.xml",
        "views/menu.xml"
    ],
    "assets": {},
    "installable": True,
    "application": False
}
