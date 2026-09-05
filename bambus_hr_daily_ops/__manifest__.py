# -*- coding: utf-8 -*-
{
    "name": "Bambus HR Daily Ops",
    "summary": "Single Kanban/Form to manage attendance corrections, time off, overtime and fines.",
    "version": "18.0.1.9.0",
    "category": "Human Resources",
    "author": "Bambus Technologies LLP",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "hr_attendance",
        "hr_holidays",
        "hr_contract",
        "hr_payroll_community",
        "hr_holidays_attendance",
        "face_attendance_custom",
    ],
    "data": [
        "views/assets.xml",
        "security/ir.model.access.csv",
        "security/attendance_sheet_rules.xml",
        "views/hr_attendance_sheet_views.xml", 
        "views/hr_employee_view.xml",
        "views/hr_attendance_view.xml",
        "data/attendance_sheet_cron.xml",
    ],

    "assets": {
        "web.assets_backend": [
            "bambus_hr_daily_ops/static/src/css/bambus_attendance_timeline.css",
            "bambus_hr_daily_ops/static/src/css/attendance_dashboard.css",
            "bambus_hr_daily_ops/static/src/css/employee_dashboard.css",
            "bambus_hr_daily_ops/static/src/css/employee_attendance.css",
            "bambus_hr_daily_ops/static/src/js/bambus_face_preview_flip.js",
            "bambus_hr_daily_ops/static/src/js/attendance_dashboard.js",
            "bambus_hr_daily_ops/static/src/js/attendance_editor.js",
            "bambus_hr_daily_ops/static/src/js/employee_dashboard.js",
            "bambus_hr_daily_ops/static/src/js/employee_attendance.js",
            "bambus_hr_daily_ops/static/src/xml/attendance_dashboard.xml",
            "bambus_hr_daily_ops/static/src/xml/attendance_editor.xml",
            "bambus_hr_daily_ops/static/src/xml/employee_dashboard.xml",
            "bambus_hr_daily_ops/static/src/xml/employee_attendance.xml",
        ],
    },



    "application": False,
    "installable": True,
}
