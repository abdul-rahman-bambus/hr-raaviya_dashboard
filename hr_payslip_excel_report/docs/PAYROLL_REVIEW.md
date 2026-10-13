# Payroll Reports

Open **HRMS → Payroll → Payroll Reports** or **Payroll → Report → Payroll Reports**. Select **Payslip Summary** (the existing
single-sheet layout) or **Payroll Review** (the new four-sheet workbook).

Choose a company enabled in your session, Current Month or a custom date range,
optional department/employees, and payslip status. Default status includes all except
rejected payslips. Only payslips fully contained in the date range are selected; the
export never prorates an overlapping month payslip to a shorter requested range.
Download Excel stays on the current Odoo screen.

## Workbook

- **Payroll Summary:** staff-type groups, employee/payslip counts, earnings, deductions,
  net pay, pending review count, and staff without a matching payslip. Currency is the
  selected company's currency. Group employee counts count distinct staff per group;
  the overall employee count is distinct across groups.
- **Employee Payroll Register:** employee identity, period/status, salary basis/rate,
  payable days, attendance/leave, actual and payable hours, salary components, deductions,
  net pay, pending reviews, and flags. Each resolved payslip has its own row in Payroll Review; Payslip Summary combines these into one row per employee. Staff with
  no matching payslip have a clearly labelled row with blank monetary amounts.
- **Attendance & Adjustments:** local-date punches, effective template, weekly-off source
  and policy, holiday classification, detected proposals, approved values, saved payslip
  detail amounts, and reviewer information.
- **Review Exceptions:** missing/uncomputed payslips, overlapping periods, missing contracts,
  unmapped payable-day buckets, pending reviews, missing punch outs, dates without an
  effective template, snapshot differences, and salary reconciliation mismatches.

All sheets have filters and no frozen rows or columns. Workbook preferences hide horizontal and vertical scrollbars; spreadsheet applications can override those preferences. Monetary/duration totals use numeric Excel
cells. Durations display HH:MM; they are Excel time values, not text or decimal hours.
Filtered totals use SUBTOTAL. Warning rows are highlighted. Formula-like employee
names and notes are written as literal strings.

## Sources and interpretation

**Salary amounts are read from payslip lines.** The exporter does not compute payslips,
change approvals, or create attendance. Missing GROSS/NET lines stay blank and are flagged.
Basic/hourly earnings use BASIC-category lines; allowances and deductions include child
categories. OT, PH/SWD, LATE/LF, and LO/SAR salary codes provide the existing overtime,
holiday/special-day pay, fines, and loan/advance breakdowns. Other salary-rule deductions
remain in Other Deductions. Credit notes reverse salary amounts. Payments/Due Amount
are intentionally omitted because this module has no verified payment ledger source.

**Payable days come from saved worked-day buckets**, excluding unpaid leave codes.
Unknown or ambiguous codes leave the figure blank with a review item. They are not
inferred by dividing salary by a daily rate. Contract salary/rate is the current value
on the payslip's contract; historical earned amounts remain the saved payslip values.

**Attendance and HR reviews are current records.** Shared Attendance Report helpers
provide work fractions, template thresholds, selected weekdays/schedule weekly offs,
public holidays, and local-date grouping. The payslip's contract provides the report
timezone/holiday calendar. Public holidays take precedence over weekly offs. Leave is
counted on scheduled working days, including half-day/hour leave fractions; remaining
working-day absence is shown separately. Present Day Equivalents include half-day work;
Half-Day Work Occurrences is a count, not another amount to add to Present.

Weekly-Off Calendar Days describe classification, not paid leave. Weekly-Off Worked
Days describe work on those dates. A template's Not Payable/All Worked Hours policy
controls additional overtime, not whether every unused weekly off is a paid day.

Approved values and proposals are shown separately, but payroll totals always reflect
what the selected payslip actually contains, including any system amounts already used
by its salary rules. Pending items and changed HR/snapshot amounts prompt review; export
never silently removes amounts from an existing payslip. Hourly payable hours use the
payslip's billable-hour figure; raw HR-updated hours appear separately in the daily sheet.

Regular payslips for the exact same employee, contract, and date range are duplicates.
Choose Done before Waiting before Draft; within the same status prefer computed GROSS/NET
lines, then the latest update and highest ID. Payroll Review lists each excluded payslip
and the selected ID. No database payslips are modified or deleted. Different contracts,
nonidentical periods, and credit notes remain included.

Payslip Summary has one row per employee. Salary totals combine resolved split periods
and reverse credit notes. Attendance for an identical period counts once and ignores
credit-note repetitions. Partially overlapping periods retain their salary totals but
leave summary day/hour figures blank for manual review. Payroll Review still shows the
underlying resolved periods and flags overlaps; its detail attendance can repeat across
those periods or credit notes.

Payroll group permissions, company scope, payslip record rules, and transient-wizard
ownership apply to the download. No payslip searches use sudo.

## Deployment and verification

Upgrade `hr_payslip_excel_report` and `attendance_custom_report` and restart Odoo so the
new menu, wizard, dependencies, and shared Python helpers load.

```sh
odoo-bin -d TEST_DATABASE \
  --db-filter='^TEST_DATABASE$' \
  -u hr_payslip_excel_report,attendance_custom_report \
  --test-enable --test-tags /hr_payslip_excel_report --stop-after-init
```

Automated tests cover salary-only staff, multiple/credit payslips, filters and date
validation, company/access rules, unpaid/half-day leave, hourly caps, local-midnight
punches, weekly-off classification, pending/approved adjustments, literal Excel strings,
workbook structure, summary compatibility, and authenticated HTTP downloads.

A reusable Chromium check also exercises the installed wizard, date/employee selection,
and actual download while checking that the Odoo web client remains mounted:

```sh
python hr_payslip_excel_report/tests/browser/verify_report_wizard.py \
  --url http://localhost:8071 --db YOUR_TEST_DATABASE --output /tmp/payroll-review.xlsx
```

It requires Playwright/Chromium, a running test Odoo instance, and this module installed.
The database name must include `test`. It creates and removes one verification employee.
Use `ODOO_TEST_LOGIN`, `ODOO_TEST_PASSWORD`, and `CHROMIUM_BIN` to override test defaults.
