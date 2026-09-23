# -*- coding: utf-8 -*-
{
    "name": "Bambus Attendance Overtime & Fine",
    "version": "18.0.3.0.0",
    "category": "Human Resources",
    "author": "Bambus Technologies LLP",
    "depends": ["hr", "hr_attendance", "hr_contract", "custom_hr_payroll"],
    "data": [
        "security/attendance_automation_security.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/hr_attendance_views.xml",

    ],
    "installable": True,
}
