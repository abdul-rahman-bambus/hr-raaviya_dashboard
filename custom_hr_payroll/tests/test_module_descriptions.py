from io import StringIO

from docutils.core import publish_doctree

from odoo.modules.module import get_manifest
from odoo.tests.common import TransactionCase


class TestModuleDescriptions(TransactionCase):
    def test_apps_descriptions_render_without_rst_warnings(self):
        for name in ('custom_hr_payroll', 'bambus_hr_daily_ops', 'hr_payslip_excel_report'):
            with self.subTest(module=name):
                description = get_manifest(name)['description']
                messages = StringIO()
                publish_doctree(description, settings_overrides={
                    'warning_stream': messages, 'halt_level': 2,
                    'file_insertion_enabled': False, 'raw_enabled': False})
                self.assertFalse(messages.getvalue())
                module = self.env['ir.module.module'].search([('name', '=', name)], limit=1)
                module._get_desc()
                self.assertTrue(module.description_html)
                self.assertNotIn('system-message', module.description_html)
