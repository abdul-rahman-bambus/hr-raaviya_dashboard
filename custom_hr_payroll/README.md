# Custom HR payroll

This module supplies contract wage types, attendance/payroll helpers and salary
revisions. The root README describes the coordinated attendance and report flow.

Runtime warning cleanup uses **18.0.4.17.0**; the bulk confirmation feature below
remains available. See [the coordinated warning-cleanup upgrade](../bambus_hr_daily_ops/docs/RUNTIME_WARNINGS.md).

## Bulk confirmation of reviewed payslips

Upgrade **custom_hr_payroll to 18.0.4.16.0**, restart Odoo and refresh the client.
Payroll officers can then use the existing Employee Payslips list:

1. Generate and compute the month's payslips using the normal batch workflow.
2. Review the final Excel, employee coverage, attendance and approved adjustments.
3. In **Employee Payslips**, select the intended **Draft/Waiting** records from
   one company, then **Actions > Confirm Payslips**.
4. Review the selected employees, periods, count and total Net salary. **Cancel**
   changes nothing. **Confirm Selected Payslips** confirms the whole selection.
5. For exports after confirmation, select **Done** or **All Except Rejected**;
   the report's Draft default excludes confirmed payslips.

Each slip runs its standard confirmation workflow, including salary computation
and any installed accounting/loan hooks. This action does not initiate bank/cash
salary payment. The standard payroll records become **Done**; batch membership,
actual attendance and saved HR approval decisions are retained.

Only computed Draft/Waiting payslips with a saved NET salary line are accepted.
Done, Rejected, uncomputed, empty or mixed-company selections are rejected.
Normal access rules apply, without sudo. All selected payslips are confirmed in
one transaction. If standard confirmation fails or any salary-rule amount changes
at currency precision, the entire selection is rolled back. Compute Sheet and
review the updated report before confirming again; there is no silent acceptance
of a changed processed salary. Native confirmation can regenerate salary-line
IDs while preserving amounts; this is not an immutable payment or attendance lock.

No existing payslips are confirmed by module upgrade. The bulk guard applies to
this list action; the original single-payslip Confirm behavior is unchanged.

## Validation

Use an isolated database containing `test` in its name for browser fixtures:

```sh
python custom_hr_payroll/tests/browser/verify_bulk_confirmation.py \
  --url http://localhost:8071 --db YOUR_TEST_DATABASE
```

Requires Playwright and Chromium. Only self-created fixture payslips are confirmed
and removed. Unit coverage includes three wage types, Cancel/open, standard hook
delegation, saved-money preservation, salary-change and second-record failure
rollback, invalid selections, access checks, state revalidation and Done exports.

Local verification: **237 Odoo tests** passed with zero failures/errors on
`raaviya_attendance_test`. The installed browser passed the native list Actions
menu, three-wage selection, Cancel, bulk Done confirmation with unchanged total
Net 3,000, unchanged unpaid flags, and a Done-status Excel download. Accounting
and loan integration behavior follows whichever standard modules are installed;
the failure regression verifies atomic rollback rather than replacing their
logic. No production/customer payslips were confirmed by these fixture tests.
