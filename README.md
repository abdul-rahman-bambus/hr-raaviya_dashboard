# Raaviya HR attendance and payroll add-ons

## Customer layout update (29 October 2026)

Upgrade `bambus_hr_daily_ops` to **18.0.1.96.0** and
`hr_payslip_excel_report` to **18.0.4.20.0**, then reload the browser.
Daily Attendance opens as a flat paginated list. Payslip Summary exports all wage
types in one sheet with a Salary Type column. Payslip Payables summary groups are
hidden; detailed attendance, earnings, deductions and salary computation remain.
These layout changes do not reprice approvals or saved salaries.


Attendance History has been replaced by independent HR decisions. Current punch
records supply actual time; dashboard edits save actual punches. See the
[coordinated migration guide](bambus_hr_daily_ops/docs/INDEPENDENT_ATTENDANCE_DECISIONS.md)
before upgrading the four attendance/payroll-report modules.


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

Upgrade `bambus_hr_attendance_ot_fine` to **18.0.3.32.0** to correct Payable Days
for worked dates whose normal special-day credit was withheld. Compute Sheet
refreshes existing draft rows: withheld work contributes zero normal paid days,
while actual work and saved approved earnings remain. See the
[withholding count correction](bambus_hr_daily_ops/docs/WITHHELD_PAYABLE_DAYS.md).

The automation form has matching Weekly Off and Public Holiday Payroll Treatment
sections. Contract wage displays, bounded review scrolling, persistent exclusions,
paid special-day counters, and separate earnings/deduction details are supported.
See the module README for details, calculations and test commands.

Daily Attendance cards include a pencil beside each employee's name to open
their actual attendance entries for the selected local date. Upgrade
`bambus_hr_daily_ops` to **18.0.1.87.0** and reload the client for this shortcut.

## Payroll workflow

Use **Payroll > Payslip Batches > Generate Payslips**, then **Payroll Reports >
Payslip Summary**. Status defaults to **Draft**; choose **All Except Rejected** if
needed and select the correct period/employees. Computed draft amounts are reportable without
confirming payslips. After attendance or HR decisions change, recompute draft
payslips before exporting. The export reads saved salary lines.

Confirmation is optional for reporting. If the month is finalized through
payslip confirmation, select **Done** or **All Except Rejected** for later exports.
Upgrade `hr_payslip_excel_report` to **18.0.4.15.0** for the Draft default.

For bulk month-end confirmation, upgrade `custom_hr_payroll` to **18.0.4.16.0**.
Select computed Draft/Waiting records in Employee Payslips, then **Actions >
Confirm Payslips**. Review the count/Net total and confirm. Standard confirmation
runs for each selection; changed salary amounts or any failure roll back all.
See [bulk confirmation and reporting](custom_hr_payroll/README.md).

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

For the Odoo 18 deprecation, metadata and startup-log corrections, see
[runtime warning cleanup and coordinated upgrade versions](bambus_hr_daily_ops/docs/RUNTIME_WARNINGS.md).
The [additional local-log cleanup](bambus_hr_daily_ops/docs/ADDITIONAL_RUNTIME_WARNINGS.md)
covers Employee Info, Loans, Salary Advances and Apps descriptions; the SaaS
client is explicitly excluded.

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

## Staging reconciliation correction (21 October 2026)

Upgrade `custom_hr_payroll` to **18.0.4.13.0**,
`bambus_hr_attendance_ot_fine` to **18.0.3.29.0**, and
`hr_payslip_excel_report` to **18.0.4.13.0**, then restart/reload as appropriate.
The custom payroll migration repairs saved header aggregates using BASIC-category
line totals, including wage-specific rule codes. It does not rewrite salary lines
or states. The attendance upgrade adapts supported BASIC_MONTHLY/BASIC_DAILY/
BASIC_HOURLY code rules to shared template normal pay while retaining conditions
and the original non-template fallback. Review these rule changes before rollout;
unrelated custom codes are untouched. Recompute affected existing drafts after
attendance/template changes. Existing finalized salary lines remain saved.

Reports now support both positive and negative deduction conventions through
saved GROSS/NET reconciliation. **Other Allowances** excludes OT and holiday pay
already shown separately. Day units remain attendance classifications/credits;
special-day base pay can use worked hours divided by calendar hours per day.
Manual dashboard Present overrides can also differ from payroll work fractions.
The export does not infer that every displayed day unit is an equal salary unit.

The restored staging investigation confirmed a Daily rule reading DAYSWORKED
only, wage-specific BASIC codes hidden by the old header, an explicit manual
Present override, changed paid-holiday configuration with older saved draft pay,
and multi-day hourly punches. These are separate causes; a blanket rounding
change would not resolve them. Correct actual punches through HR review, retain
approved snapshots, and recompute drafts instead of creating duplicates.

See [the three-wage manual test](bambus_hr_daily_ops/docs/MANUAL_PAYROLL_TEST.md)
from the root README, or locate `docs/MANUAL_PAYROLL_TEST.md` in daily operations.

## Reviewed attendance exceptions (22 October 2026)

Monthly/Daily templates now offer **Day Pay for Reviewed Attendance Exceptions**.
The default keeps actual-hours classification. Opting into **Regularize Reviewed
Exception Time** lets saved session-specific HR decisions cover missing scheduled
time for day pay, while approved fines remain separate and punches stay intact.
Hourly rules retain their own payable-hour review. Half Day Leave now suggests
the missing half and asks HR to confirm the half and paid/unpaid Time Off type.
The last approval clears the review filter; rate displays include correct units.
No threshold tolerance change is included.

See [configuration, manual cases and upgrade versions](bambus_hr_daily_ops/docs/REVIEWED_EXCEPTION_DAY_PAY.md).

## Partial attendance salary treatment

Templates now offer **Use Half/Full-Day Thresholds** (existing behaviour) or
**Normal Day Pay Minus Approved Fines** for Monthly/Daily regular working dates.
The latter gives normal attendance-day pay for completed positive scheduled work
and deducts only saved approved fines, including a missing session. Actual work
hours, Hourly calculations, paid special-day policies and explicit leave remain
separate. Recompute existing drafts after selecting the option.

See [configuration, upgrade versions and expected payslip amounts](bambus_hr_daily_ops/docs/PARTIAL_ATTENDANCE_SALARY.md).

Daily Attendance wage badges identify Monthly (blue), Daily (amber) and Hourly
(purple) contracts without grouping cards. Missing wage type uses a neutral
label. Badges read the date-specific contract wage type supplied by the dashboard;
attendance status colours and saved payroll/approval values are unchanged.
