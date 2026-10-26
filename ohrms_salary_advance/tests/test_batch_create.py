from odoo.tests.common import TransactionCase


class TestAdvanceBatchCreate(TransactionCase):
    def test_batch_and_single_requests_keep_unique_sequences_and_values(self):
        workers = self.env['hr.employee'].create([{'name': 'Advance batch one'}, {'name': 'Advance batch two'}])
        requests = self.env['salary.advance'].create([
            {'employee_id': workers[0].id, 'advance': 100},
            {'employee_id': workers[1].id, 'advance': 200}])
        single = self.env['salary.advance'].create({'employee_id': workers[0].id, 'advance': 50})
        self.assertEqual(requests.employee_id, workers)
        self.assertEqual(requests.mapped('advance'), [100, 200])
        self.assertEqual(len(set((requests | single).mapped('name'))), 3)
        self.assertTrue(all(name.startswith('SAR') for name in (requests | single).mapped('name')))
        self.assertEqual(set(requests.mapped('state')), {'draft'})

    def test_state_changes_keep_chatter_tracking(self):
        worker = self.env['hr.employee'].create({'name': 'Advance tracking worker'})
        request = self.env['salary.advance'].with_context(tracking_disable=False, mail_notrack=False).create(
            {'employee_id': worker.id, 'advance': 100})
        self.env.flush_all()
        self.env.cr.precommit.run()
        request.write({'state': 'submit'})
        self.env.flush_all()
        self.env.cr.precommit.run()
        self.assertTrue(request.message_ids.tracking_value_ids.filtered(
            lambda value: value.field_id.name == 'state'))
