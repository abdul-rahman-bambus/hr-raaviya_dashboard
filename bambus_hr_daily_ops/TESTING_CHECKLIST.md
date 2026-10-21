# Attendance Automation Test Checklist

This checklist records the automated coverage for attendance automation and the
remaining acceptance checks that require a running Odoo database and browser.

## Current release evidence and remaining gaps

The 20 October 2026 calendar-month candidate passed **167 Odoo tests**
(zero failures/errors), **8 OWL Chromium tests**, and installed paid-day checks
using an October wage / 31 divisor. The new regression class covers 28/29/30/31
full months, leap February, partial employment, periods crossing months,
absence/paid/unpaid leave, paid weekly offs/public holidays, salary-derived
reviews and fines, local-date boundaries, Daily/Hourly rates, fixed rates and
preserved approved snapshots/final salary lines.

The prior isolated flat-30 check (12,400 pay for a 12,000 contract over 31 dates)
is historical. The client selected actual calendar days on 20 October, and all
four full-month regressions now produce 12,000. Deployment reconciliation is
still needed. See [release readiness](docs/GO_LIVE_READINESS.md) for remaining
gaps; the September run below is retained as historical evidence.

The known manual dashboard-entry gap is not covered as a working punch-creation
flow by the existing suites. A passing suite must not be read as proof that a
manually entered dashboard time triggers automatic fines or reaches payroll.

## Automated scenarios

Run the module with Odoo's test runner and the `bambus_hr_daily_ops` test tag:

```bash
./odoo-bin -d <test_database> --test-enable --stop-after-init \
  -u bambus_hr_daily_ops --test-tags /bambus_hr_daily_ops
```

The end-to-end test fixture creates its own UTC work calendar, employees,
contracts, automation templates, attendance punches, attendance-sheet lines,
and attendance update wizards. It does not depend on production employee data.

### Historical verified run (28 September 2026)

The suite was executed on 28 September 2026 against an Odoo 18 test database
with both integration modules upgraded:

```bash
./odoo-bin -c raaviya_automation_test.conf -d raaviya_automation_test \
  --test-enable --stop-after-init \
  -u bambus_hr_attendance_ot_fine,bambus_hr_daily_ops \
  --test-tags /bambus_hr_daily_ops --log-level=test --workers=0
```

Result: **28 tests, 0 failures, 0 errors**. The database still reported
unrelated migration/configuration warnings for legacy field parameters,
duplicate payslip field labels, and the non-installable `bambus_saas_client`
module; these warnings did not fail the attendance automation suite and should
be resolved separately before production deployment.

- [x] Resolve the company default template when an employee has no template.
- [x] Prefer an effective employee template over the company default.
- [x] Fall back to the company default when the employee template is expired.
- [x] Apply late-entry grace to detected late minutes and fine values.
- [x] Apply an assigned template without requiring legacy company OT mode or
  contract OT/fine switches.
- [x] Suppress overtime below the configured 60-minute minimum.
- [x] Accept exactly 60 minutes as one payable overtime hour.
- [x] Disable overtime and late/fine detection when their rules are disabled.
- [x] Resolve `0–9,000` salary to `75` per overtime hour.
- [x] Resolve `9,000.01–12,000` salary to `100` per overtime hour.
- [x] Resolve salary above `12,000` to `120` per overtime hour.
- [x] Carry the resolved template, salary basis, slab, rate, and amount into the
  HR attendance update.
- [x] Preserve a saved rate/amount snapshot after the contract wage changes.
- [x] Use the changed contract wage for a new overtime update.
- [x] Apply a configurable fixed OT start and end window using exact minutes.
- [x] Propose all worked hours when weekly-off work is configured as payable.
- [x] Propose all worked hours when public-holiday work is configured as payable.
- [x] Reject overlapping salary slabs.
- [x] Assign an automation template to existing employees.
- [x] Allow HR to update proposed overtime and fine hours.
- [x] Open OT and Fine review dialogs directly from filtered dashboard rows,
  populate detected values, and save the resulting rate/amount snapshots.
- [x] Filter OT/Fine metric results in place without launching a nested client
  action or losing the current Odoo action metadata.
- [x] Store HR-saved overtime calculation details.
- [x] Save a regularized fine with a zero deduction.
- [x] Derive a monthly employee's late fine per minute from daily salary and
  date-specific scheduled minutes.
- [x] Create and revoke half-day absence/leave corrections.
- [x] Revoke full-day absence and leave corrections.
- [x] Keep hourly employees out of the absence workflow.
- [x] Verify every OT calculation choice: fixed, per hour, half day, full day,
  regularize, and 1x/1.5x/2x salary.
- [x] Verify every fine calculation choice, including salary per minute.
- [x] Verify exact, 15-minute, 30-minute, and 60-minute OT rounding.
- [x] Verify contract, fixed-template, and salary-slab OT rate policies.
- [x] Verify public-holiday all-hours and no-additional-OT policies.
- [x] Verify every public-holiday calculation choice and its saved sheet snapshot.
- [x] Verify contract, fixed-template, salary-multiplier, and salary-slab
  public-holiday rate policies.

The plain-language [user guide](docs/ATTENDANCE_AUTOMATION_USER_GUIDE.md),
[manual scenarios](docs/ATTENDANCE_AUTOMATION_MANUAL_TESTING.md), and
[automated coverage matrix](docs/ATTENDANCE_AUTOMATION_TEST_MATRIX.md) explain
the inputs and expected results without requiring knowledge of the source code.

## Weekly-off regression coverage

The automated suite also covers all seven selected weekdays, schedule-based
fallback, employee/company precedence, effective dates, historical contracts,
date-limited and alternating-week schedules, strict Not Payable behavior,
clearing existing overtime, public-holiday overlap, and payroll bucket refresh.
The `attendance_custom_report` suite compares payroll/report counts and reads a
generated XLSX workbook to verify the selected day is classified as weekly off.
Run the report suite with the attendance automation modules installed to execute
its optional template integration tests:

```bash
./odoo-bin -c <config> -d <isolated_test_database> --http-port=8070 \
  -u custom_hr_payroll,bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report \
  --test-enable --test-tags /bambus_hr_daily_ops,/custom_hr_payroll,/attendance_custom_report \
  --stop-after-init --log-level=test --workers=0
```

## Required browser/UAT checks

- [ ] Confirm only employees from the selected company appear in the assignment
  wizard and that the selector cannot create employees.
- [ ] Confirm authorized HR users can update values while employees remain read-only.
- [ ] Confirm the dashboard OT and Fine metrics open the correctly filtered rows
  and each row opens its update dialog without navigating through History.
- [ ] Confirm dates and hours render correctly in the deployment timezone.
- [ ] Confirm saved overtime and fine values appear once in a generated
  payslip and are not duplicated after recomputation.
- [ ] Confirm rejected and regularized entries do not affect net pay.
- [ ] Confirm the employee Salary Overview shows only that employee's payslips.
- [ ] Capture final screenshots after the workflow and labels are signed off.

## Expected client examples

| Contract basic salary | One saved OT hour | Expected amount |
| ---: | ---: | ---: |
| 9,000.00 | 1 hour | 75.00 |
| 10,000.00 | 1 hour | 100.00 |
| 13,000.00 | 1 hour | 120.00 |

For a monthly salary of `12,000` on an eight-hour date, daily salary is `400`
and the per-minute fine rate is `400 / 480`. Ten final fine minutes therefore
produce a deduction of `8.33` before currency rounding.

The optional minimum is inclusive: `59` overtime minutes are suppressed and
`60` overtime minutes become `1.00` payable overtime hour when a 60-minute
minimum is configured. Templates can instead use exact-minute OT windows. Saved records keep
their salary/rate snapshot; a later basic-salary change applies only to new
proposals and saved updates.

## Paid-day dashboard labels

- Eligible Sunday/no attendance: Paid Weekly Off; disable its paid switch: Not Marked.
- Configured Monday holiday: Paid Public Holiday only with its paid switch enabled.
- Overlap: holiday precedence, including when holiday payment is disabled.
- Contractless/Daily/Hourly or out-of-contract dates: no Monthly paid label.
- Existing attendance, leave and explicit HR statuses retain their status.
- Paid labels filter correctly and do not inflate Present/punch/Not Marked counts.
- Removing manual Absent restores the derived paid label.

## Paid-day withholding and restoration

- Confirm requires a reason for withhold and restore; Cancel writes nothing.
- Confirm immediately shows Unpaid Weekly Off / Unpaid Public Holiday without
  marking Absent or inflating Not Marked/Present/punch counts.
- Reload preserves the decision; Logs shows HR actor, timestamp and reason.
- Worked attendance stays Present with hours and Paid-off Credit Withheld.
- Draft normal pay, paid-credit rows and report counts exclude the rejected date;
  approved OT, holiday extra pay and fines remain unchanged.
- Restore follows current settings, including switches disabled after withholding.
- Holiday/weekly-off overlap cannot be rejected/paid through the wrong bucket.
- Other dates/employees remain eligible. Daily/Hourly, out-of-contract or regular
  working dates cannot receive a paid-day rejection.
- Non-HR and other-company requests fail; HR cannot edit/delete audit records.
- Recalculation retains exclusions; finalized salary lines remain unchanged.
- Run the installed `verify_paid_day_withholding.py` scenario on an isolated test DB.

## Standard payroll workflow after preparation rollback

- The Prepare Draft Payroll menu and added batch shortcuts are absent after upgrade.
- The original Generate Payslips action computes Draft salary lines.
- Payroll Reports > Payslip Summary includes Draft and separates wage types.
- Report values match saved computed salary; exporting does not mark payroll paid.
- Existing draft/finalized batches, payslips and salary lines survive upgrade.
- Recompute existing drafts after attendance/HR changes; do not regenerate duplicates.

## Hourly payroll corrections

- Edit a completed punch by seconds, recompute its existing draft and compare
  salary/hours with a fresh test payslip; preserve precision before money rounding.
- Add/delete/move/close punches and check refreshed work rows, hours and days.
  Multiple punches on one local date count once; open/zero-hour entries count zero.
- Check per-date caps, local month boundaries, employee/worker contract types,
  unrelated custom work codes, and unchanged finalized/cancelled salary lines.
- Check Hourly Present/Payable Days in both exports against attended dates, even
  for short shifts. Export must not update saved salary. Recompute after edits.
- Recheck Monthly/Daily normal pay and approved special-day earnings.

## Restored staging acceptance

Follow [three-wage manual acceptance](docs/MANUAL_PAYROLL_TEST.md). Verify typed
BASIC header totals, both deduction sign conventions/refunds, separate Other
Allowances, Daily worked special-day base pay, and saved-line preservation during
upgrade. Confirm changing template flags alone does not rewrite saved salaries.
