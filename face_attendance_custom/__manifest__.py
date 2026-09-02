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
        "hr",
        "hr_attendance"
    ],
    "external_dependencies": {
        "python": ["geopy"],
    },
    "data": [
        "security/face_attendance_security.xml",
        "security/ir.model.access.csv",
        "views/attendance.xml",
        "views/employee.xml"
    ],

    "demo": [],
    "qweb": [],
    "installable": True,
    "application": True,
    "auto_install": False,

}
