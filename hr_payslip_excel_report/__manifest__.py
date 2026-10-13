
{
    "name": "HR Payslip Excel Report",
    "version": "18.0.4.5.0",
    "summary": "HR Payslip Excel Report",
    "author": "Bambus Technologies LLP",
    "license": "LGPL-3",
    "category": "Human Resources",
    "depends": [
        "hr_payroll_community",
        "custom_hr_payroll",
        "hr_attendance",
        "hr_timesheet",
        "hr_contract",
        "attendance_custom_report",
        "bambus_hr_daily_ops",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/payroll_excel_wizard.xml",
    ],
    "installable": True,
    "application": False
}
