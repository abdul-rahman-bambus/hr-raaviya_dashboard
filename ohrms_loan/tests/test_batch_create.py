from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLoanBatchCreate(TransactionCase):
    def test_batch_and_single_create_keep_names_order_and_amounts(self):
        workers = self.env['hr.employee'].create([{'name': 'Batch loan one'}, {'name': 'Batch loan two'}])
        loans = self.env['hr.loan'].create([
            {'employee_id': workers[0].id, 'loan_amount': 1000},
            {'employee_id': workers[1].id, 'loan_amount': 2000}])
        single = self.env['hr.loan'].create({'employee_id': workers[0].id, 'loan_amount': 500})
        self.assertEqual(loans.employee_id, workers)
        self.assertEqual(loans.mapped('loan_amount'), [1000, 2000])
        names = (loans | single).mapped('name')
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(name.startswith('LO/') for name in names))
        self.assertEqual(set(loans.mapped('state')), {'draft'})

    def test_approved_pending_loan_still_blocks_later_item_in_same_batch(self):
        worker = self.env['hr.employee'].create({'name': 'Pending batch loan'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['hr.loan'].create([
                {'employee_id': worker.id, 'loan_amount': 1000, 'state': 'approve', 'balance_amount': 1000},
                {'employee_id': worker.id, 'loan_amount': 500}])
        self.assertFalse(self.env['hr.loan'].search([('employee_id', '=', worker.id)]))

    def test_existing_approved_loan_still_blocks_creation(self):
        worker = self.env['hr.employee'].create({'name': 'Existing pending loan'})
        loan = self.env['hr.loan'].create({'employee_id': worker.id, 'loan_amount': 1000, 'state': 'approve'})
        loan.action_compute_installment()
        self.assertEqual(loan.balance_amount, 1000)
        with self.assertRaises(ValidationError):
            self.env['hr.loan'].create({'employee_id': worker.id, 'loan_amount': 500})
