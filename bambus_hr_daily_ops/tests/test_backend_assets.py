from pathlib import Path

from odoo.modules.module import load_information_from_description_file
from odoo.tests.common import TransactionCase


class TestBackendAssets(TransactionCase):
    """Guard client actions against silently disappearing from the bundle."""

    def test_dashboard_client_actions_are_bundled(self):
        manifest = load_information_from_description_file("bambus_hr_daily_ops")
        backend_assets = manifest["assets"]["web.assets_backend"]

        expected_assets = {
            "bambus_hr_daily_ops/static/src/js/attendance_dashboard.js",
            "bambus_hr_daily_ops/static/src/js/employee_dashboard.js",
            "bambus_hr_daily_ops/static/src/js/employee_attendance.js",
        }
        self.assertTrue(expected_assets.issubset(set(backend_assets)))

        module_root = Path(__file__).parents[1]
        registrations = {
            "static/src/js/attendance_dashboard.js": "bambus_attendance_dashboard",
            "static/src/js/employee_dashboard.js": "bambus_employee_dashboard",
            "static/src/js/employee_attendance.js": "bambus_employee_attendance",
        }
        for relative_path, action_key in registrations.items():
            source = (module_root / relative_path).read_text(encoding="utf-8")
            self.assertIn(f'.add("{action_key}"', source)
