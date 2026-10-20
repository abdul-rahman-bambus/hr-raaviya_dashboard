# Payroll reports and monthly draft preparation

## Prepare draft payroll

Open **HRMS > Payroll > Prepare Draft Payroll**, choose the company and a date in
its payroll month, and optionally select a department or employees. Any date in
the month selects the entire calendar month, including February and leap years.
An empty employee selection means all active employees in that company/department.

1. **Generate Missing Drafts** creates or reuses the matching open monthly batch,
   computes missing payslips using the existing payslip engine, and leaves them
   in **Draft**. Compatible existing drafts are reused without recomputing their
   saved salary lines. Unassigned matching drafts may be attached to the batch.
2. Review the **Attention** results. Missing contracts/structures, conflicting
   payslips, contract overlaps, computation errors and report review exceptions
   are listed. Successful employees are retained if another employee cannot be
   computed; failed employee creation is rolled back. Pending HR adjustments
   remain excluded from pay until approved under the existing rules.
3. After attendance, paid-day decisions or HR approvals change, explicitly select
   **Recompute Drafts**. It refreshes eligible draft payslips in this batch and
   employee scope. Waiting, finalized, cancelled and refund payslips are excluded.
   Existing manual inputs and unrelated worked-day codes retain their existing
   computation behavior; this action does not approve adjustments.
4. **Payroll Report** opens the existing report wizard filtered to this batch,
   period, employee scope and **Draft** status. Download Excel for verification.
   Salary values are the saved payslip salary lines, not a second calculation.
   The report header includes the selected batch. **Open Batch** shows its slips.

The same preparation action is available on an open, non-refund monthly batch.
The original **Generate Payslips**, confirmation and reporting flows remain
available for other customers. A batch's separate **Payroll Report** shortcut
opens all its non-cancelled statuses, preserving ordinary finalized-payroll use.

## Eligibility and duplicate protection

- Only Running/Expired (`open`/`close`) contracts overlapping the month are
  eligible; Draft/Cancelled contracts are flagged as unavailable. A salary
  structure is required. With accounting installed, a company salary/general
  journal must be configured even though these payslips are not posted.
- Joining/leaving dates clip the payslip to the contract's portion of the month.
  Sequential non-overlapping contracts produce separate contract-period slips.
  Monthly salary still uses the full calendar month's divisor, not segment length.
- Repeated preparation reuses the batch and exact employee/contract/period drafts.
  Other-batch drafts are not moved. Overlaps, multiple existing payslips or an
  existing waiting/finalized payslip flag that employee for manual review.
  No payslip is overwritten, reopened, cancelled or deleted by generation.
- A closed matching batch is protected. Multiple matching batches require opening
  the intended batch explicitly. Refund batches are outside this workflow.
- Company-level transaction locking serializes automation runs. Access checks,
  selected-company boundaries and existing employee/payroll record rules remain
  in effect; preparation does not use sudo to bypass payroll permissions.

Nothing confirms a payslip, closes a batch, posts accounting, emails an employee
or records cash/bank payment. Draft results may change after recomputation: retain
the exact report used for cash payment as the payment-period record.

The separate dashboard manual-time-entry/punch-detection limitation remains;
verify real attendance records and HR approvals before preparing payment figures.

## Deployment and scope

Restart Odoo and upgrade **hr_payslip_excel_report to 18.0.4.10.0**, then reload the
web client. The feature is an explicit payroll-officer action, not a scheduled
monthly job. Existing data is not automatically regenerated on upgrade.

This is the automation stage. Payroll report layout revisions and the requested
PDF version are the next stage; the existing Excel reports are reused here.

## Verification

Use an isolated database. Standard module tests cover month lengths, repeat
preparation, explicit recompute, report parity with saved salary lines and the
legacy generator, split contracts, missing configuration, protected records,
company/role access, individual failure rollback, pending reviews and withholding.

```sh
python odoo-bin -c <test.conf> -d <test_database> -u hr_payslip_excel_report \
  --test-enable --test-tags /hr_payslip_excel_report --stop-after-init
python hr_payslip_excel_report/tests/browser/verify_draft_payroll.py \
  --url http://localhost:8071 --db <test_database>
```

The installed-browser scenario creates a dedicated test company/employee and
removes its fixtures. It verifies Generate Missing Drafts, repeat/no duplicate,
explicit attendance recompute, Draft/batch report defaults and a real XLSX download.

Validation on 20 October 2026: the full payroll/attendance suite passed **183
Odoo tests**. After the final non-payment/default refinement, all **11 focused
preparation tests** passed. The installed-browser automation scenario passed,
including a real Excel download. The pre-existing installed report-wizard scenario
also passed both Excel exports and its legacy filtering checks. These checks do not establish production
rollout or client approval of the payment figures.
