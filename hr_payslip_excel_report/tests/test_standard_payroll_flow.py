"""Keep the original generator and Draft summary usable after withdrawing PR #121."""
import io
import zipfile
from xml.etree import ElementTree as ET

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestStandardPayrollFlow(TransactionCase):
    def test_standard_batch_computes_draft_and_summary_reads_saved_salary(self):
        employee = self.env['hr.employee'].create({'name': 'Standard batch report employee'})
        structure = self.env['hr.payroll.structure'].create({
            'name': 'Standard batch report structure', 'code': 'STD_BATCH_TEST', 'parent_id': False,
            'rule_ids': [(6, 0, [self.env.ref('hr_payroll_community.' + name).id
                                for name in ('hr_rule_basic', 'hr_rule_taxable', 'hr_rule_net')])]})
        self.env['hr.contract'].create({
            'name': 'Standard batch report contract', 'employee_id': employee.id,
            'date_start': '2026-09-01', 'wage_type': 'monthly', 'wage': 12000,
            'struct_id': structure.id, 'state': 'open'})
        batch = self.env['hr.payslip.run'].create({
            'name': 'Standard September payroll', 'company_id': self.env.company.id,
            'date_start': '2026-09-01', 'date_end': '2026-09-30'})
        generator = self.env['hr.payslip.employees'].with_context(active_id=batch.id).create({
            'employee_ids': [(6, 0, employee.ids)]})
        generator.action_compute_sheet()
        slip = batch.slip_ids
        self.assertEqual(len(slip), 1)
        self.assertEqual((batch.state, slip.state, slip.paid), ('draft', 'draft', False))
        net = slip.line_ids.filtered(lambda line: line.code == 'NET')
        self.assertTrue(net)
        saved = [(line.id, line.total) for line in slip.line_ids]
        report = self.env['payslip.excel.wizard'].create({
            'report_type': 'summary', 'duration_type': 'custom',
            'start_date': '2026-09-01', 'end_date': '2026-09-30',
            'employee_ids': [(6, 0, employee.ids)]})
        self.assertEqual(report._selected_payslips(), slip)
        row = self.env['report.hr_payslip_excel_report.payroll_review']._data(report)['register'][0]
        self.assertEqual(row['net'], net.total)
        with zipfile.ZipFile(io.BytesIO(report._generate_xlsx())) as workbook:
            root = ET.fromstring(workbook.read('xl/workbook.xml'))
            ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            names = [sheet.attrib['name'] for sheet in root.findall('m:sheets/m:sheet', ns)]
            self.assertEqual(names, ['Payslip Summary'])
        self.assertEqual([(line.id, line.total) for line in slip.line_ids], saved)
        self.assertEqual((slip.state, slip.paid), ('draft', False))

    def test_withdrawn_preparation_ui_is_absent(self):
        self.assertNotIn('payroll.draft.preparation', self.env)
        for name in ('menu_draft_payroll_preparation', 'action_draft_payroll_preparation',
                     'draft_payroll_preparation_form', 'payslip_run_draft_payroll_form'):
            self.assertFalse(self.env.ref('hr_payslip_excel_report.' + name, raise_if_not_found=False))
        model = self.env['hr.payslip.run']
        view = model.get_view(self.env.ref('hr_payroll_community.hr_payslip_run_view_form').id, 'form')
        self.assertNotIn('action_prepare_draft_payroll', view['arch'])
        self.assertNotIn('action_open_payroll_report', view['arch'])
        self.assertIn('Generate Payslips', view['arch'])
        self.assertNotIn('batch_id', self.env['payslip.excel.wizard']._fields)
        self.assertIn('company_id', model._fields)  # preserve stored batch ownership
