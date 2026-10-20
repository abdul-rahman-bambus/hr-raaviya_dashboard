# Repository guidance

This repository contains Odoo 18 HR, attendance, payroll, and reporting add-ons.
Read the root README and the affected module documentation before changing behavior.

## Attendance and payroll invariants

- `hr.attendance` contains actual punch records used by automatic detection.
  `bambus.hr.attendance.sheet.line` holds HR daily snapshots and saved approvals.
  An HR audit log is not itself a punch record.
- The dashboard's `update_dashboard_attendance` currently saves the sheet snapshot
  and time audit only. It does not create/update `hr.attendance` or invoke detection.
  This is a known go-live gap; do not document manual dashboard entry as a complete
  punch-to-fine/payroll workflow until it is fixed and tested.
- Resolve templates per attendance date: effective employee template, effective
  company template, then legacy fallback. Respect company and contract boundaries.
- Paid Weekly Offs and Paid Public Holidays give normal paid-day credit to Monthly
  contracts only, despite the shortened labels. Keep underlying field names and
  saved values stable. Weekly-off credit defaults on; public-holiday credit defaults
  off. Neither creates leave requests or consumes leave balances.
- Weekly Off Policy and Public Holiday Policy independently control additional
  work earnings. The paid-day booleans do not replace those policies. Weekly-off
  rates come from the Overtime tab; holidays have their own calculation/rate policy.
- Count an overlapping public holiday/weekly off once, using holiday precedence.
  Keep normal credit and approved extra pay separate. A 2x additional earning plus
  normal day credit can total 3x for a full special day.
- Detection is a proposal. With an effective template, unapproved extra pay/fines
  do not become payroll amounts. Preserve approved snapshots and saved exclusions;
  Ignore/Delete is persisted only by Approve Remaining Items. Cancel discards it.
- Compare actual daily worked hours to the effective day thresholds. Do not cap
  classification hours at a shorter schedule and make a fixed full-day target
  unreachable. Reports and payroll must agree on day classification.
- Compute Sheet refreshes generated worked-day rows for draft/verification
  payslips, preserves unrelated custom codes, and avoids double-counted paid days.
  Do not silently rewrite finalized salary lines.
- Monthly daily salary uses `hr.contract._get_monthly_daily_rate(day)`: wage divided
  by calendar days in the local attendance date's month (28/29/30/31). Payroll,
  per-minute fine detection and salary-derived HR review rates share this helper.
  Do not reintroduce a flat 30, use worked days as the denominator, or divide by a
  partial payslip/employment range. Cross-month periods price each date separately.
  Daily/Hourly wages and fixed rates keep their existing rules. Preserve saved
  approvals and finalized salary lines; new proposals and draft normal pay use
  the calendar-month basis. Client selected this rule on 20 October 2026.

## Validation and documentation

Use an isolated database whose name contains `test` for browser fixture scripts.
They create and remove employees, calendars, templates and payroll records.
Do not use production records for automated fixtures.

Run the relevant Odoo tests; example from an Odoo source checkout:

```sh
python odoo-bin -c <test.conf> -d <test_database> --test-enable --stop-after-init \
  -u custom_hr_payroll,bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report,hr_payslip_excel_report \
  --test-tags /custom_hr_payroll,/bambus_hr_daily_ops,/attendance_custom_report,/hr_payslip_excel_report
```

For backend form changes, target `/bambus_hr_daily_ops:TestBackendAssets` and check
rendered labels in the installed client. For client changes, run the production
OWL Chromium tests and the relevant installed-browser script. Commands and
prerequisites are in `bambus_hr_daily_ops/README.md`.

Keep user-facing labels, module versions, README, attendance approvals guide and
release checklist consistent. Record actual test counts and remaining gaps; local
test success does not establish deployment or client acceptance. Keep runtime
logs, scratch scripts and screenshots in `work/`, outside commits.
