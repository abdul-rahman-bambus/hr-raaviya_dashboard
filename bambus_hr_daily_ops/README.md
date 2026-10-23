# Bambus HR Daily Ops

## Current delivered flow and release readiness

The original planned go-live was **Monday 19 October 2026**. The calendar-month
salary rule was selected on **20 October 2026**. Read the
[release readiness review](docs/GO_LIVE_READINESS.md) before rollout; automated
checks do not resolve the documented dashboard manual-entry gap.

The changes delivered through PRs #113–#116 include:

- Viewport-bounded combined review scrolling and visible mobile approval controls.
- Contract Daily Wage / Hourly Rate / Monthly Wage display on attendance rows and reviews.
- Separate normal paid special-day credits and approved additional work earnings.
- Paid Weekly Offs (enabled by default) and Paid Public Holidays (disabled by default).
  Both apply only to Monthly contracts even though the labels omit “(Monthly)”.
- Whole normal-day credit on paid special days, with or without attendance;
  approved worked hours add earnings under the applicable OT/holiday policy.
- Actual-hour day classification, refreshed draft worked-day rows on Compute Sheet,
  and paid-credit rows that top up rather than duplicate worked-day fractions.
- Matching Weekly Off / Public Holiday Payroll Treatment sections, persistent
  Ignore/Delete decisions, and reconciled paid-day columns in reporting.

### Why keep Weekly Off Policy?

| Control | Purpose |
| --- | --- |
| Paid Weekly Offs | Normal paid-day credit for eligible Monthly employees |
| Weekly Off Policy | Additional earnings proposed for actual weekly-off work |
| Paid Public Holidays | Normal paid-holiday credit for eligible Monthly employees |
| Public Holiday Policy | Additional earnings proposed for actual holiday work |

The booleans and work policies are independent. Not Payable suppresses additional
weekly-off OT, not normal paid-day credit. All Worked Hours uses the Overtime
tab's calculation/rate and requires the Overtime Rule and HR approval. Public
holidays have independent calculation/rate settings. Public-holiday precedence
prevents duplicate normal credit on an overlapping weekly off.

In a 30-day month, a Monthly wage of 12,000 gives daily pay of 400. With 8 scheduled
hours/day, 8 approved special-day hours at 1x add 400 to normal credit (800 total);
at 2x they add 800 (1,200 total). Confirm whether a client means double **extra**
pay or double **total** pay before selecting a multiplier. No leave allocation,
leave request or leave balance is created by these paid-day booleans.

### Calendar-month salary basis

Use Monthly wage / calendar days in the local attendance date's month:

| Month length | Daily rate on a 12,000 Monthly contract | Full eligible month normal pay |
| --- | --- | --- |
| 28 | 428.571429 | 12,000 |
| 29 | 413.793103 | 12,000 |
| 30 | 400 | 12,000 |
| 31 | 387.096774 | 12,000 |

Keep the rate unrounded during regular-pay aggregation; monetary adjustment
amounts use the existing currency precision. The divisor is not the number of
working days, employment days or days selected in a payslip. A 15-day eligible
period in leap-year February is 12,000 × 15 / 29. A payslip covering 30 January
through 2 February 2024 is 2 × 12,000 / 31 + 2 × 12,000 / 29.

Each normal paid-day credit, detected per-minute fine and salary-derived HR
review uses the shared contract helper. Monthly base eligibility, unpaid/paid
leave, weekly-off/holiday policy and work fractions still apply; a full salary
requires all dates to be eligible for normal pay. The change does not create pay
for missing regular attendance or extend contract dates. Daily/Hourly contracts,
fixed rates and salary-slab thresholds are unchanged.

Restart Odoo and upgrade `custom_hr_payroll` to `18.0.4.11.0`,
`bambus_hr_attendance_ot_fine` to `18.0.3.26.0`, and `bambus_hr_daily_ops` to
`18.0.1.81.0`. Recompute draft payslips and review new proposals. Previously
approved extra pay/fines remain saved snapshots; they are not silently repriced.
Finalized salary lines are not rewritten automatically.


### Paid-day dashboard labels

On dates without punches, leave or an explicit HR status, the attendance dashboard
shows **Paid Weekly Off** or **Paid Public Holiday** for eligible Monthly contracts.
It uses payroll's effective employee/company template, paid-day switches, contract
dates and holiday calendar. A public holiday takes precedence over a weekly off;
if holiday payment is disabled, an overlapping Sunday does not become a paid
weekly off. Disabled/ineligible dates retain **Not Marked**. Filters support both
paid labels, and these dates are excluded from Not Marked counts. Present and
punch counters stay unchanged. These are derived display statuses: no attendance,
leave allocation or approval is created. Removing an HR status refreshes the label.
Upgrade `bambus_hr_daily_ops` to `18.0.1.82.0` and reload the web client.


### Withhold or restore one employee's paid day

On **Attendance**, find the employee and date, then select **Withhold Paid Day**.
Enter a required reason and select **Confirm**. Cancel saves nothing. The action
is available for eligible Monthly weekly offs/public holidays; it does not disable
the template for other employees or dates.

- No punches: the status immediately becomes **Unpaid Weekly Off** or
  **Unpaid Public Holiday**, rather than Not Marked.
- Worked date: attendance and worked hours remain visible with
  **Paid-off Credit Withheld**. Actual worked-day statistics are retained.
- **Restore Paid Day** requires a reason and reapplies the current template,
  contract and calendar rules. If payment is now disabled, restoration removes
  the exception but the date remains Not Marked instead of becoming paid.
- **Logs** retains each withhold/restore action, the HR user, timestamp and reason.
  HR cannot edit/delete individual decision records or create them outside the
  validated action. Company access and the dashboard's existing HR/contract
  permissions still apply.

Withholding removes the date's normal special-day credit, including the normal
worked-hours fallback on that date. It does **not** reject approved OT or fines,
change punches, mark Absent, create leave, or consume a leave balance. Use the
existing review to reject additional earnings/deductions separately. A holiday
on a weekly off uses the holiday decision only; it never falls back to weekly-off
payment. Decisions are scoped to employee, date and special-day type and survive
attendance recalculation. Restoring never overrides a disabled template switch.

Paid-day counters and normal-pay statistics reflect the decision; attendance
reports use the same eligibility helpers and payroll exports use payslip totals.
Run **Compute Sheet** on draft payslips to refresh generated credit rows and
salary lines. Already finalized salary lines are not automatically rewritten.
For example, on a 12,000 Monthly contract in October, withholding one otherwise
paid date removes 12,000 / 31 (about 387.10) from normal pay; separately approved
extra pay and fines retain their saved amounts.

For worked dates, upgrade `bambus_hr_attendance_ot_fine` to **18.0.3.32.0** and
recompute drafts so withheld worked fractions also leave generated payable-day
rows. Actual special-day work statistics/hours and approved amounts remain.
Both payroll workbooks use those saved rows. See the
[withheld Payable Days correction](docs/WITHHELD_PAYABLE_DAYS.md).

Restart Odoo, upgrade `bambus_hr_attendance_ot_fine` to `18.0.3.27.0` and
`bambus_hr_daily_ops` to `18.0.1.83.0`, then reload the client. Existing employees
have no withheld dates on upgrade. This feature does not fix the separate manual
dashboard punch/detection gap documented below.

### Standard payroll batches and draft reports

Create/open **Payroll > Payslip Batches**, fill in the name and period, then use
**Generate Payslips** to select employees and compute their payslips. Keep them
Draft for this customer's review workflow. Open **Payroll Reports**, choose
**Payslip Summary**, the period/employees and **Draft** (or **All Except Rejected**),
then download Excel. Monthly, Hourly and Daily sheets remain separate.

Recompute draft payslips after attendance or approvals change. Downloading a
report reads saved salary lines; it does not recompute or record cash payment.
The separate Prepare Draft Payroll wizard has been withdrawn. Upgrade
`hr_payslip_excel_report` to `18.0.4.11.0` and reload Odoo to remove its shortcuts.
The upgrade retains existing payroll data. See the
[payroll guide](../hr_payslip_excel_report/README.md).

### Manual dashboard time entry: current limitation

`update_dashboard_attendance` currently writes the HR daily sheet snapshot and
time-audit log, not `hr.attendance`. Therefore Present status, displayed times
and HR Update logs can exist while Punched In / Punched Out and automatic fines
remain zero. Editing those displayed times is not yet a complete punch correction
workflow. Correct actual attendance records through the standard Attendances /
existing punch-management flow, review detected adjustments, and recompute draft
payroll. Do not duplicate a punch that already exists. The intended dashboard
repair still needs implementation and acceptance testing.

### Verification commands

Use a disposable test database, never live employee records. From an Odoo checkout
with this repository on `addons_path`:

```sh
python odoo-bin -c <test.conf> -d <test_database> --test-enable --stop-after-init \
  -u custom_hr_payroll,bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report,hr_payslip_excel_report \
  --test-tags /custom_hr_payroll,/bambus_hr_daily_ops,/attendance_custom_report,/hr_payslip_excel_report
```

From this repository, with Playwright and Chromium installed (the withholding
download check also requires `openpyxl`):

```sh
ODOO_SOURCE=/path/to/odoo python -m unittest discover -s bambus_hr_daily_ops/tests/browser -v
python bambus_hr_daily_ops/tests/browser/verify_combined_review.py --url http://localhost:8071 --db <test_database>
python bambus_hr_daily_ops/tests/browser/verify_reviewed_day_pay.py --url http://localhost:8071 --db <test_database>
python bambus_hr_daily_ops/tests/browser/verify_reviewed_day_pay.py --fine-only --url http://localhost:8071 --db <test_database>
python bambus_hr_daily_ops/tests/browser/verify_paid_special_days.py --url http://localhost:8071 --db <test_database>
python bambus_hr_daily_ops/tests/browser/verify_paid_day_labels.py --url http://localhost:8071 --db <test_database>
python bambus_hr_daily_ops/tests/browser/verify_paid_day_withholding.py --url http://localhost:8071 --db <test_database>
```

Browser fixtures verify actual records and the full installed asset bundle; they
remove their own fixtures. `ODOO_TEST_LOGIN` / `ODOO_TEST_PASSWORD` select test
credentials (default admin/admin); do not put real credentials into documentation.

## Attendance automation templates

HR Managers maintain reusable rule masters under **HRMS > Configuration >
Automation Rules**. A template contains effective dates, late-entry and
early-exit grace periods, break allowance, minimum overtime, weekend/holiday
overtime, and the default calculation methods and rates.

A template can be assigned to multiple employees. Resolution is deliberately
simple: the employee template is used first; otherwise the employee's company
default template is used. Expired, future, inactive, or missing templates fall
back to the legacy company/contract settings. Shift start, end, and work periods
continue to come from the employee's work schedule, while employee-specific
wage and statutory rates continue to come from the contract.

The resolved template affects automatic detection and supplies defaults to the
HR update dialogs. The system proposes values; authorized HR users may correct
the hours, method, and rate before saving the final attendance result.
Assigning an active template is sufficient to activate its OT and fine rules;
legacy company OT-mode and contract eligibility switches remain fallbacks only
for employees without a template.

Overtime can start at shift end, after a configurable offset, or at a fixed
clock time. It can have no end, a fixed end time, or a maximum duration, with
exact-minute or block rounding. Half-day hours and full-day classification are
also template driven so schedules of different lengths remain valid full days.
Weekly-off and public-holiday policies are independent and can either suppress
overtime or propose every valid worked hour for HR review.

### Attendance settings now live on templates

With the attendance automation module installed, global Day Allocations, Work
Hour Rules, and Overtime Mode controls are hidden in Settings. Keep using
**Default Automation Rules** to select the company template. Configure late
and post-break grace, half/full-day thresholds, and overtime on the template.
Day-classification fields remain editable even when overtime is disabled.

Payroll and XLSX summaries use the effective template's day thresholds.
Stored template late minutes already include per-session grace; summaries no
longer deduct the legacy global grace a second time. Existing saved global
values remain available only to compatibility paths without an effective template.
The standalone custom payroll module retains its original settings view.

In **Hourly Pay**, enable **Use Template Hour Limit** to override the existing
contract cap. Set **Hourly Wage Hour Limit** to the maximum billable hours per
local day; zero means no cap. Raw punches remain unchanged. Existing templates
keep their contract caps until this override is enabled, avoiding a silent pay
change during upgrade. The same cap applies to detected and HR-reviewed hours.

Upgrade all four affected modules: `custom_hr_payroll`,
`bambus_hr_attendance_ot_fine`, `bambus_hr_daily_ops`, and
`attendance_custom_report` (if installed).

### Template-driven weekly off

Configure **Weekly Off** on each attendance automation template:

- **Assigned Working Schedule** classifies dates without assigned work periods
  as weekly off. It uses the contract valid for the date, including alternating
  weeks and date-limited work periods, and falls back to the employee schedule.
  Public holidays and personal leave do not change the weekly-off classification.
- **Selected Weekdays** uses only the selected Monday–Sunday checkboxes,
  even when the working schedule contains a shift on a selected day. An empty
  selection means no weekly-off days.
- **Not Payable** proposes no weekly-off overtime. **All Worked Hours** proposes
  every worked hour for HR review when the Overtime Rule is enabled, subject
  to the template's minimum overtime threshold.

The effective employee template takes precedence over the company template.
Inactive or out-of-date templates fall back to the effective company template,
then to the assigned working schedule when neither is effective. Attendance,
payslip statistics, and attendance XLSX reports use this same date classification.
A public holiday that overlaps weekly off uses the public-holiday policy and
bucket, so the day is counted once.

Upgrade `custom_hr_payroll`, `bambus_hr_attendance_ot_fine`,
`bambus_hr_daily_ops`, and `attendance_custom_report` (if installed). The legacy
Weekend Configuration and OT for Weekend and Festival controls are removed
from settings; their stored global values no longer determine attendance or
reporting. Existing templates default to Assigned Working Schedule and retain
their explicit Weekly Off Policy. Configure Selected Weekdays on the relevant
company/employee templates if the old global weekday selections must be kept.
The hidden legacy weekend-overtime toggle no longer overrides Not Payable.
Review and recompute draft attendance/payroll after changing a template;
HR-approved attendance snapshots remain the authoritative payroll amounts.

### Salary-based overtime rates

Set **OT Rate Policy** to **Salary Range / Slab** to derive the hourly overtime
rate from the contract salary valid for the attendance date. Monthly, daily,
and hourly contract values are supported as salary bases. Slabs use inclusive
lower and upper limits; an unchecked **Has Maximum** creates the final
open-ended range. Overlapping ranges and multiple open-ended slabs are rejected.
Salary-slab rates are always applied per OT hour, so the template hides the
otherwise redundant calculation-method choice and the daily update defaults to
**Fixed Amount per Hour**.

Example: `0–9,000 = 75/hour`, `9,000.01–12,000 = 100/hour`, and
`12,000.01–No Limit = 120/hour`. Saved entries keep a snapshot of the
template, salary basis, matched slab, rate, hours, and amount, so later contract
salary changes affect new proposals without changing historical saved updates.

Use **Assign Existing Employees** on the template to select active employees
from the template company. The assigned list is read-only and never creates an
employee; employee creation remains in the Employees workflow.

## Overtime and late/fine update flow

Attendance punches and the employee's work schedule produce proposed overtime
and late/fine hours.  These proposals do not become authoritative payroll
amounts until HR reviews and saves them.

1. The attendance engine calculates overtime and late/fine hours.
2. The daily attendance sheet marks the proposal as `Needs Review`.
3. HR clicks the dashboard **Overtime** or **Late / Fine** metric to list only
   affected employees, then opens **OT** or **Fine** directly on the employee row.
4. The update dialog shows the system-calculated hours separately from the
   editable final hours.
5. HR selects a calculation method, adjusts the rate when applicable, reviews
   the automatically calculated amount, and clicks **Save Changes**.
6. Payroll uses the saved attendance-sheet hours and amount.

This is attendance maintenance, not a request/approval chain. Template
configuration remains restricted to HR managers, while authorized HR users can
correct and save daily attendance values.

### Calculation methods

| Method | Calculation |
| --- | --- |
| Fixed Amount | The entered amount is used once. |
| Fixed Amount per Hour | Final hours multiplied by the entered rate. |
| Half Day | Half of the employee's daily salary. |
| Full Day | The employee's daily salary. |
| Regularize | Zero payment or deduction. |
| 1x Salary | Final hours multiplied by the derived hourly salary. |
| 1.5x Salary | Final hours multiplied by 1.5 times hourly salary. |
| 2x Salary | Final hours multiplied by 2 times hourly salary. |

For hourly contracts, the configured hourly rate is used. For daily contracts,
the daily wage is divided by scheduled hours. For monthly contracts, daily pay
is monthly wage divided by the calendar days in that attendance date's month
(28/29/30/31), and hourly pay is that result divided by scheduled hours. Existing contract overtime and late-fine rates provide the defaults for
fixed-per-hour updates.

The default **Per Minute from Daily Salary** fine method divides the applicable
daily salary by the employee's scheduled working minutes for that date, then
multiplies that rate by the final fine minutes after grace. Monthly salary uses
the actual calendar-month daily-rate basis; daily contracts use their daily wage.
Hourly contracts produce no late fine under this method.

### State meanings

- **No Exception**: no calculated value is awaiting review.
- **Needs Review**: the system has proposed hours for HR review.
- **Updated**: the HR-saved hours, method, rate, and amount are final
  for payroll.
- **Excluded**: the proposal must not affect payroll.

### Audit principle

The attendance calculation supplies a recommendation; the saved update stores
the HR correction. The update saves the selected method and rate
along with the final hours and amount so the payroll result can be explained
later.

## Testing

For a step-by-step Sunday example and automated regression command, see
[Weekly Off Verification](docs/WEEKLY_OFF_VERIFICATION.md).

The automated suite creates isolated employees, contracts, schedules,
attendance punches, templates, salary slabs, and saved attendance records for
the main company-default and employee-override scenarios. See
[`TESTING_CHECKLIST.md`](TESTING_CHECKLIST.md) for automated coverage, expected
client examples, and the browser/UAT checks to complete before release.

## Plain-language documentation

- [Attendance Automation User Guide](docs/ATTENDANCE_AUTOMATION_USER_GUIDE.md)
- [Attendance Automation Manual Testing](docs/ATTENDANCE_AUTOMATION_MANUAL_TESTING.md)
- [Attendance Automation Automated Test Matrix](docs/ATTENDANCE_AUTOMATION_TEST_MATRIX.md)

### Generate DOCX and PDF with embedded screenshots

1. Save the approved screenshots in `docs/screenshots/` using the names in the
   manual testing guide.
2. Install `pandoc` and `libreoffice`.
3. Run `python3 docs/generate_documentation.py --require-screenshots` from the
   module directory.
4. Collect the finished DOCX and PDF files from `docs/output/`. Screenshots are
   embedded in those files; recipients do not need the source image folder.

## Approved values in Attendances and payroll

The standard Attendances list keeps punch-level detected OT/Fine values and now
also shows read-only **HR Approved** columns. Because one day can contain several
punch sessions, the approved daily result is displayed only on the final
attendance row for that employee and date. This prevents list totals and exports
from multiplying one daily approval across multiple punches.

The daily attendance sheet line remains the authoritative HR snapshot. With an effective template, payroll uses approved OT/fine amounts and excludes
pending or ignored amounts. Legacy paths retain their compatibility behavior.
Reports follow the same precedence and use the review-line link shown on the
final attendance row.

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

See `bambus_hr_daily_ops/docs/MANUAL_PAYROLL_TEST.md` for the three-wage
manual test entries and expected results.

## Reviewed attendance exceptions (22 October 2026)

Monthly/Daily templates now offer **Day Pay for Reviewed Attendance Exceptions**.
The default keeps actual-hours classification. Opting into **Regularize Reviewed
Exception Time** lets saved session-specific HR decisions cover missing scheduled
time for day pay, while approved fines remain separate and punches stay intact.
Hourly rules retain their own payable-hour review. Half Day Leave now suggests
the missing half and asks HR to confirm the half and paid/unpaid Time Off type.
The last approval clears the review filter; rate displays include correct units.
No threshold tolerance change is included.

See [configuration, manual cases and upgrade versions](docs/REVIEWED_EXCEPTION_DAY_PAY.md).

### Daily Attendance return navigation

Version **18.0.1.85.0** adds a **Daily Attendance** button beside the date/History
controls whenever a filter or search is active. It clears that filter/search and
resets the page while preserving the selected date. After the last review is
saved, automatic return now covers **Late / Fine** and **Overtime**, as well as
the **To Review** filters. Remaining reviews still take priority. Upgrade the
daily-operations module and reload the web client to load the new assets.

## Partial attendance salary treatment

Templates now offer **Use Half/Full-Day Thresholds** (existing behaviour) or
**Normal Day Pay Minus Approved Fines** for Monthly/Daily regular working dates.
The latter gives normal attendance-day pay for completed positive scheduled work
and deducts only saved approved fines, including a missing session. Actual work
hours, Hourly calculations, paid special-day policies and explicit leave remain
separate. Recompute existing drafts after selecting the option.

See [configuration, upgrade versions and expected payslip amounts](docs/PARTIAL_ATTENDANCE_SALARY.md).
