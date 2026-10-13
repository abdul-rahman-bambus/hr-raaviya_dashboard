# Payroll Reports

Open **HRMS → Payroll → Payroll Reports** or **Payroll → Report → Payroll Reports**. Select **Payslip Summary** (salary-type employee sheets and final totals) or **Payroll Review** (the new four-sheet workbook).

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

## Detailed employee summary

Payslip Summary includes the reference workbook's CTC/contract salary, gross salary,
payable/present days, weekly-off leave and absence, worked/OT/fine hours, basic pay,
system overtime, total earnings, system fine, and net pay. It additionally separates
public-holiday days, public-holiday worked days, public-holiday pay, and weekly-off worked
days, while retaining allowances and total deductions.

The summary displays hours as numeric decimal hours (1.75 means 1h 45m). The detailed
review workbook continues to use numeric Excel durations displayed as HH:MM.

Total CTC / Contract Salary is the monthly salary on the selected contract, matching the
reference's monthly salary concept; it is not annual employer cost. On the Monthly sheet it remains blank for multiple differing monthly salaries. The
Hourly sheet instead shows Hourly Rate (per Hour) from contract.hourly_rate, and the
Daily sheet shows Daily Wage (per Day) from contract.daily_wage. A rate is displayed once
per employee, rather than added across split payslips. Gross Salary and Total Earnings both use the
saved GROSS line in this payroll flow. System Overtime uses OT, System Fine uses LATE/LF,
and Public Holiday Pay uses PH alone, excluding the broader SWD special-day allowance.

Week-off Leave Days are unworked weekly-off equivalents from the effective template or
assigned schedule, not a claim of paid leave entitlement. Public holidays take precedence
and are counted separately. Present/absent/holiday figures and actual worked hours use
the same daily attendance/leave classifications in both report modes. Payable Days still
comes from saved payroll buckets; none of these display changes recalculates salary.

## Salary-type sheet separation

Payslip Summary downloads **Monthly**, **Hourly**, **Daily**, and **Final Summary**, in that
order. All three detail tabs remain present even when a type has no matching employees.
Salary type comes from each selected payslip's contract `wage_type`, not the employee's
current contract or translated labels. Missing/unsupported salary types are reported as
a validation error rather than silently putting someone in the wrong sheet; Payroll
Review remains available to inspect missing contracts.

Each detail tab has one row per employee within that salary type and the existing
attendance, holiday, and salary columns. If an employee has different salary types
across the selected periods, the appropriate amounts appear on each respective tab.
Row numbering starts at one on each sheet. Duplicate-period selection, credit notes,
company filters, record rules, and public-holiday precedence continue to apply.

The last sheet has exactly three data rows: **Monthly**, **Hourly**, and **Daily**. It
shows employee counts and totals of all numeric detail columns, including the displayed contract salary/rates, days, hours, public-holiday pay, earnings,
fines, deductions, and net pay. Totals use available values; a populated type with wholly unavailable amounts
remains blank, while an empty type totals zero. Employee counts are distinct within
each type, not a global count across all types.

Final Summary uses formulas linked to the detail-tab subtotal cells, with cached values
for readers that do not calculate formulas. Applying filters on a detail tab updates its
corresponding final-summary totals in Excel. This adds no separate grand-total row.
Rows/columns remain unfrozen and the workbook's scrollbar preferences are preserved.
The separate Payroll Review export retains its audit-oriented four-sheet structure.

## Contract salary and daily/hourly rates

The first monetary column uses the matching contract field and a heading with its units:
Monthly: Total CTC / Contract Salary (`wage`); Hourly: Hourly Rate (per Hour)
(`hourly_rate`); Daily: Daily Wage (per Day) (`daily_wage`). Zero configured rates remain
numeric zero. If selected payslips for one employee have different rates, the single
summary rate is blank and the row flags Multiple contract rates; Payroll Review shows
each underlying rate. No rate is inferred from earned salary.

The Final Summary column is Contract Salary / Rate Total and links to each detail
subtotal. Its hourly/daily values are sums of the displayed configured rates, not earned
wages or payroll expense. Gross Salary, Total Earnings, deductions, and Net Pay continue
to come from saved payslip amounts. Cell comments explain the different rate units.
