from ast import literal_eval
from pathlib import Path
from xml.etree import ElementTree

from odoo.tests.common import TransactionCase


class TestBackendAssets(TransactionCase):
    """Guard client actions against silently disappearing from the bundle."""

    def test_dashboard_client_actions_are_bundled(self):
        module_root = Path(__file__).parents[1]
        manifest = literal_eval(
            (module_root / "__manifest__.py").read_text(encoding="utf-8")
        )
        backend_assets = manifest["assets"]["web.assets_backend"]

        expected_assets = {
            "bambus_hr_daily_ops/static/src/js/attendance_dashboard.js",
            "bambus_hr_daily_ops/static/src/js/attendance_editor.js",
            "bambus_hr_daily_ops/static/src/js/employee_dashboard.js",
            "bambus_hr_daily_ops/static/src/js/employee_attendance.js",
        }
        self.assertTrue(expected_assets.issubset(set(backend_assets)))

        registrations = {
            "static/src/js/attendance_dashboard.js": "bambus_attendance_dashboard",
            "static/src/js/attendance_editor.js": "bambus_attendance_editor",
            "static/src/js/employee_dashboard.js": "bambus_employee_dashboard",
            "static/src/js/employee_attendance.js": "bambus_employee_attendance",
        }
        for relative_path, action_key in registrations.items():
            source = (module_root / relative_path).read_text(encoding="utf-8")
            self.assertIn(f'.add("{action_key}"', source)

        editor_template = (module_root / "static/src/xml/attendance_editor.xml").read_text(encoding="utf-8")
        self.assertIn('t-if="!employee.is_hourly"', editor_template)

    def test_employee_dashboard_is_nested_under_hrms(self):
        module_root = Path(__file__).parents[1]
        hrms_tree = ElementTree.parse(module_root / "views/hrms_menu.xml")
        hrms_menu = hrms_tree.find(".//menuitem[@id='menu_bambus_hrms_root']")
        self.assertIsNotNone(hrms_menu)
        self.assertEqual(hrms_menu.get("name"), "HRMS")
        attendance_parent = hrms_tree.find(
            ".//menuitem[@id='menu_bambus_hrms_attendance']"
        )
        self.assertIsNotNone(attendance_parent)
        self.assertEqual(attendance_parent.get("parent"), "menu_bambus_hrms_root")

        employee_tree = ElementTree.parse(module_root / "views/hr_employee_view.xml")
        employee_menu = employee_tree.find(".//menuitem[@id='menu_bambus_employees_root']")
        self.assertIsNotNone(employee_menu)
        self.assertEqual(employee_menu.get("parent"), "menu_bambus_hrms_root")

        attendance_tree = ElementTree.parse(module_root / "views/hr_attendance_sheet_views.xml")
        attendance_menu = attendance_tree.find(
            ".//menuitem[@id='menu_bambus_hr_attendance_editor']"
        )
        self.assertIsNotNone(attendance_menu)
        self.assertEqual(attendance_menu.get("parent"), "menu_bambus_hrms_attendance")
        self.assertEqual(attendance_menu.get("action"), "action_bambus_hr_attendance_editor")

    def test_hrms_navigation_contains_core_hr_workflows(self):
        module_root = Path(__file__).parents[1]
        navigation_tree = ElementTree.parse(module_root / "views/hrms_navigation.xml")
        expected_menus = {
            "menu_bambus_hrms_dashboard",
            "menu_bambus_hrms_time_off",
            "menu_bambus_hrms_payroll",
            "menu_bambus_hrms_configuration",
            "menu_bambus_hrms_public_holidays",
        }
        menu_ids = {
            menu.get("id") for menu in navigation_tree.findall(".//menuitem")
        }
        self.assertTrue(expected_menus.issubset(menu_ids))
        for menu_id in expected_menus:
            menu = navigation_tree.find(f".//menuitem[@id='{menu_id}']")
            expected_parent = (
                "menu_bambus_hrms_configuration"
                if menu_id == "menu_bambus_hrms_public_holidays"
                else "menu_bambus_hrms_root"
            )
            self.assertEqual(menu.get("parent"), expected_parent)

        holiday_action = navigation_tree.find(
            ".//record[@id='action_bambus_hrms_public_holidays']"
        )
        self.assertIsNotNone(holiday_action)
        holiday_model = holiday_action.find("./field[@name='res_model']")
        self.assertEqual(holiday_model.text, "resource.calendar.leaves")
        holiday_domain = holiday_action.find("./field[@name='domain']")
        self.assertIn("('calendar_id', '=', False)", holiday_domain.text)

        holiday_form = navigation_tree.find(
            ".//record[@id='view_bambus_hrms_public_holiday_form']"
        )
        holiday_form_arch = holiday_form.find("./field[@name='arch']")
        visible_fields = {
            field.get("name") for field in holiday_form_arch.findall(".//field")
        }
        self.assertEqual(visible_fields, {"name", "date_from", "date_to"})

        holiday_calendar = navigation_tree.find(
            ".//record[@id='view_bambus_hrms_public_holiday_calendar']"
        )
        self.assertIsNotNone(holiday_calendar)
        calendar_arch = holiday_calendar.find("./field[@name='arch']/calendar")
        self.assertEqual(calendar_arch.get("date_start"), "date_from")
        self.assertEqual(calendar_arch.get("date_stop"), "date_to")
        self.assertEqual(calendar_arch.get("mode"), "month")
        view_mode = holiday_action.find("./field[@name='view_mode']")
        self.assertEqual(view_mode.text, "calendar,list,form")

        for menu_id in {
            "menu_bambus_hrms_attendance_history",
            "menu_bambus_hrms_punch_logs",
        }:
            menu = navigation_tree.find(f".//menuitem[@id='{menu_id}']")
            self.assertIsNotNone(menu)
            self.assertEqual(menu.get("parent"), "menu_bambus_hrms_attendance")

    def test_attendance_log_fields_are_optional(self):
        module_root = Path(__file__).parents[1]
        for relative_path in {
            "models/hr_attendance_sheet.py",
            "models/hr_employee.py",
        }:
            source = (module_root / relative_path).read_text(encoding="utf-8")
            self.assertIn("def optional_value(", source)
            self.assertNotIn("attendance.checkin_reverse_address", source)
            self.assertNotIn("attendance.checkout_reverse_address", source)

        editor_source = (module_root / "static/src/js/attendance_editor.js").read_text(
            encoding="utf-8"
        )
        editor_template = (module_root / "static/src/xml/attendance_editor.xml").read_text(
            encoding="utf-8"
        )
        self.assertIn('"create_half_day_leave"', editor_source)
        self.assertIn('"revoke_dashboard_status"', editor_source)
        self.assertIn("this.createHalfDayLeave(employee)", editor_template)
        self.assertIn("this.toggleAbsent(employee)", editor_template)
        self.assertIn("this.toggleLeave(employee)", editor_template)
        self.assertIn("applyStatusTransition", editor_source)
        self.assertIn("openAdjustment(employee, adjustment)", editor_source)
        self.assertIn('"get_dashboard_adjustment"', editor_source)
        self.assertIn('"save_dashboard_adjustment"', editor_source)
        self.assertIn('class="o_baa_modal"', editor_template)
        self.assertNotIn('views: action.views || [[false, "form"]]', editor_source)
        self.assertNotIn("await this.load(this.state.data.date);", editor_source)

        attendance_sheet_source = (
            module_root / "models/hr_attendance_sheet.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("leave.action_draft()", attendance_sheet_source)
        self.assertNotIn('write({"state": "draft"})', attendance_sheet_source)
        self.assertIn('write({"state": "cancel"})', attendance_sheet_source)

    def test_dashboard_metric_cards_filter_in_place(self):
        module_root = Path(__file__).parents[1]
        dashboard_source = (
            module_root / "static/src/js/attendance_dashboard.js"
        ).read_text(encoding="utf-8")

        self.assertIn("openMetric(metric)", dashboard_source)
        self.assertIn("this.state.statusFilter = metric;", dashboard_source)
        self.assertIn("this.state.currentPage = 1;", dashboard_source)
        self.assertIn("Math.max(Number(value) || 0, 0)", dashboard_source)
        self.assertNotIn('tag: "bambus_attendance_editor"', dashboard_source)
