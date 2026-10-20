# Raaviya HR attendance and payroll add-ons

Custom Odoo 18 modules for employee attendance, HR adjustment review, payroll,
and attendance/payroll reporting.

| Module | Responsibility |
| --- | --- |
| `custom_hr_payroll` | Contract wage types, salary revisions and base attendance/payroll helpers |
| `bambus_hr_attendance_ot_fine` | Effective automation templates, detection, paid-day credits and payroll totals |
| `bambus_hr_daily_ops` | Attendance dashboard, combined review, audits, payslip details and configuration UI |
| `attendance_custom_report` | Attendance XLSX reports and Monthly Summary |
| `hr_payslip_excel_report` | Payroll review, detail and summary workbooks |

## Current flow

Actual attendance punches and the effective template produce OT/fine proposals.
HR approves or excludes adjustments in one combined review. Payroll uses saved
HR amounts, and Compute Sheet refreshes generated worked-day rows before salary
computation. Approved attendance values and reports follow the same precedence.

Paid Weekly Offs and Paid Public Holidays provide Monthly employees normal day
credit, with or without attendance. They are separate from the policies governing
additional work earnings. Weekly-off credit defaults enabled; public-holiday
credit defaults disabled. These labels no longer include “(Monthly)”; eligibility
still applies only to Monthly contracts. No leave request/allocation is required.
The dashboard shows Paid Weekly Off / Paid Public Holiday on eligible unmarked
dates using the same payroll checks, with public-holiday precedence.
HR can withhold or restore one employee's normal paid-off credit for one date,
with a required reason and audit history. Withheld unworked dates show Unpaid
Weekly Off / Unpaid Public Holiday; worked dates keep attendance and a withheld
indicator. Payroll and reports respect the exception; approved OT/fines remain
separate. Recompute draft payslips after the decision.

The automation form has matching Weekly Off and Public Holiday Payroll Treatment
sections. Contract wage displays, bounded review scrolling, persistent exclusions,
paid special-day counters, and separate earnings/deduction details are supported.
See the module README for details, calculations and test commands.

## Payroll workflow

Use **Payroll > Payslip Batches > Generate Payslips**, then **Payroll Reports >
Payslip Summary**. Include **Draft** or **All Except Rejected** status and select
the correct period/employees. Computed draft amounts are reportable without
confirming payslips. After attendance or HR decisions change, recompute draft
payslips before exporting. The export reads saved salary lines.

The separate Prepare Draft Payroll flow has been withdrawn. Upgrade
`hr_payslip_excel_report` to `18.0.4.11.0` to remove its installed menu/buttons;
existing batches, payslips and salary data are retained. See the
[payroll reporting guide](hr_payslip_excel_report/README.md).

## Monthly salary basis

Monthly daily pay is **Monthly wage / calendar days in the attendance month**.
February uses 28 or 29; other months use 30 or 31. The same basis supplies normal
paid-day credits, per-minute fine detection and salary-derived adjustment rates.
A full eligible month on a 12,000 contract produces 12,000 normal pay; missing
or unpaid workdays still reduce pay under the attendance rules. Partial contracts
and payslips use the full month's divisor, and periods crossing months price
each date using its own month. Daily/Hourly wages and fixed rates are unchanged.
Saved HR approvals are retained rather than automatically repriced.

## Documentation and release status

- [Contributor guidance](AGENTS.md)
- [Attendance module README](bambus_hr_daily_ops/README.md)
- [Approval and payroll rules](bambus_hr_daily_ops/docs/ATTENDANCE_APPROVALS.md)
- [Release readiness and remaining gaps](bambus_hr_daily_ops/docs/GO_LIVE_READINESS.md)
- [Test checklist](bambus_hr_daily_ops/TESTING_CHECKLIST.md)

**Known go-live blocker:** manual times entered through the dashboard currently
save the HR daily snapshot/audit without creating/updating actual attendance
punches or invoking automatic fine/OT detection. Do not assume dashboard-entered
times have completed the punch-to-payroll flow. The readiness document also tracks
calendar-month salary rollout and rounding checks requiring client verification.

Upgrade the affected modules in the target Odoo deployment, reload the client,
confirm effective company/employee templates and salary rules, and recompute draft
payslips. This repository and its tests do not establish that production has been
deployed or approved for go-live.

## Hourly attendance refresh

For Hourly contracts, **Compute Sheet** refreshes stored billable hours and
attendance days before computing draft/verification salary and generated work
rows. After adding, editing, deleting or closing actual punches, recompute the
existing draft; do not generate duplicate payslips. Completed punches with
positive worked time count once per local check-in date, including short shifts.
Open and zero-hour entries do not count. Daily caps apply after summing that
date’s punches; raw attendance and time precision are preserved.

Hourly **Payable Days** uses the last-computed attendance-date count. Report
**Present Days** reads current completed attendance dates, without half-day
fractions. If attendance changed, recompute the draft before exporting to align
the saved salary/payable totals and current attendance. Exports do not recompute
salary. Finalized/cancelled salary lines remain untouched. Monthly and Daily
classification and paid-off rules retain their existing behavior.
