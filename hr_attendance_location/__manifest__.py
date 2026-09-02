# -*- coding: utf-8 -*-
{
    "name": "Bambus Attendance Map Location",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "author": "Bambus Technologies LLP",
    "depends": ["hr", 
                "hr_attendance", 
                "hr_contract", 
                #"custom_hr_payroll"
                ],
    "data": [
        "security/ir.model.access.csv",
        "views/hr_attendance_views.xml",

    ],
    "assets": {
        "web.assets_backend": [
            "hr_attendance_location/static/src/js/attendance_location_map.js",
            "hr_attendance_location/static/src/xml/attendance_location_map.xml",
            "hr_attendance_location/static/src/scss/attendance_location_map.scss",
        ],
    },
    "installable": True,
}