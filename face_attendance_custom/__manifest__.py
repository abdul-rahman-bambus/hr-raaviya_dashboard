{
    "name": "Face attendance custom",
    "version": "18.0.0.1",
    "summary": "This module has face attendance customisation",
    "author": "cube48 AG",
    "sequence": 1,
    "description": "This module has face attendance customisation",
    "license": "LGPL-3",
    "category": "hr",
    "depends": [
        "base",
        "web",
        "bus",
        "hr",
        "hr_attendance"
    ],
    "external_dependencies": {
        "python": ["geopy"],
    },
    "data": [
        "security/face_attendance_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/attendance.xml",
        "views/employee.xml",
        "views/res_config_settings_views.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "face_attendance_custom/static/lib/leaflet/leaflet.css",
            "face_attendance_custom/static/lib/leaflet/leaflet.js",
            "face_attendance_custom/static/lib/leaflet-routing-machine/leaflet-routing-machine.css",
            "face_attendance_custom/static/lib/leaflet-routing-machine/leaflet-routing-machine.min.js",
            "face_attendance_custom/static/src/scss/employee_live_tracking_map.scss",
            "face_attendance_custom/static/src/xml/employee_live_tracking_map.xml",
            "face_attendance_custom/static/src/js/employee_live_tracking_map.js",
            "face_attendance_custom/static/src/xml/attendance_route_map.xml",
            "face_attendance_custom/static/src/js/attendance_route_map.js",
        ],
    },

    "demo": [],
    "qweb": [],
    "installable": True,
    "application": True,
    "auto_install": False,

}
