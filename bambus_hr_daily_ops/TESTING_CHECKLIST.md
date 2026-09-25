# Attendance Automation Test Checklist

This checklist records the automated coverage for attendance automation and the
remaining acceptance checks that require a running Odoo database and browser.

## Automated scenarios

Run the module with Odoo's test runner and the `bambus_hr_daily_ops` test tag:

```bash
./odoo-bin -d <test_database> --test-enable --stop-after-init \
  -u bambus_hr_daily_ops --test-tags /bambus_hr_daily_ops
```

The end-to-end test fixture creates its own UTC work calendar, employees,
contracts, automation templates, attendance punches, attendance-sheet lines,
and approval wizards. It does not depend on production employee data.

- [x] Resolve the company default template when an employee has no template.
- [x] Prefer an effective employee template over the company default.
- [x] Fall back to the company default when the employee template is expired.
- [x] Apply late-entry grace to detected late minutes and fine values.
- [x] Suppress overtime below the configured 60-minute minimum.
- [x] Accept exactly 60 minutes as one payable overtime hour.
- [x] Disable overtime and late/fine detection when their rules are disabled.
- [x] Resolve `0–9,000` salary to `75` per overtime hour.
- [x] Resolve `9,000.01–12,000` salary to `100` per overtime hour.
- [x] Resolve salary above `12,000` to `120` per overtime hour.
- [x] Carry the resolved template, salary basis, slab, rate, and amount into HR
  approval.
- [x] Preserve an approved rate/amount snapshot after the contract wage changes.
- [x] Use the changed contract wage for a new overtime approval.
- [x] Reject overlapping salary slabs.
- [x] Assign an automation template to existing employees.
- [x] Allow HR to update proposed overtime and fine hours.
- [x] Store manager-approved overtime calculation details.
- [x] Approve a regularized fine with a zero deduction.
- [x] Create and revoke half-day absence/leave corrections.
- [x] Revoke full-day absence and leave corrections.
- [x] Keep hourly employees out of the absence workflow.

## Required browser/UAT checks

- [ ] Confirm only employees from the selected company appear in the assignment
  wizard and that the selector cannot create employees.
- [ ] Confirm HR User can review proposals but only HR Manager can approve them.
- [ ] Confirm the dashboard OT and Fine metrics open the correctly filtered rows.
- [ ] Confirm dates and hours render correctly in the deployment timezone.
- [ ] Confirm approved overtime and fine values appear once in a generated
  payslip and are not duplicated after recomputation.
- [ ] Confirm rejected and regularized entries do not affect net pay.
- [ ] Confirm the employee Salary Overview shows only that employee's payslips.
- [ ] Capture final screenshots after the workflow and labels are signed off.

## Expected client examples

| Contract basic salary | One approved OT hour | Expected amount |
| ---: | ---: | ---: |
| 9,000.00 | 1 hour | 75.00 |
| 10,000.00 | 1 hour | 100.00 |
| 13,000.00 | 1 hour | 120.00 |

The configured minimum is inclusive: `59` overtime minutes are suppressed and
`60` overtime minutes become `1.00` payable overtime hour. Approved records keep
their salary/rate snapshot; a later basic-salary change applies only to new
proposals and approvals.
