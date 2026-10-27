# Payroll reports: standard batch workflow

**18.0.4.16.0** removes eager test imports from normal startup; Odoo still discovers
the report tests in test mode. The Draft default and report behavior remain.
See [runtime cleanup and upgrade versions](../bambus_hr_daily_ops/docs/RUNTIME_WARNINGS.md).

The separate Prepare Draft Payroll flow introduced in PR #121 has been withdrawn
at the client's request. Use the existing batch generator and reports.

1. Open **Payroll > Payslip Batches**, create/open the appropriate batch, and fill
   in its **Name** and period. Save the batch.
2. Select **Generate Payslips**, select eligible employees and generate. The
   standard generator computes salary lines and leaves payslips Draft.
3. Review the employee coverage, attendance and HR-approved adjustments. If data
   changes, open the affected draft payslips and use **Compute Sheet** before
   downloading again. The report does not recalculate salary.
4. Open **Payroll > Payroll Reports**, select **Payslip Summary**, the matching
   period/employees. Status defaults to **Draft**; select **All Except Rejected**
   if multiple states are needed, then
   **Download Excel**. Payslips must fall entirely within the selected dates.

Payslip Summary contains **Monthly**, **Hourly**, **Daily** and **Final Summary**
sheets. Normal paid weekly-off/public-holiday credits follow the template rules;
approved additional holiday pay is shown separately. Payroll Review remains a
separate option for detailed attendance/approval checks and review exceptions.

Generating a batch does not confirm payslips or record cash payment. Keep the
actual Excel used for cash payment as the payment-period record. Only approved
adjustments are payable under effective templates. The separate manual-dashboard
punch/detection gap remains documented in the attendance module.

Confirmation is not required to export computed Draft payslips. After reviewing
the final month totals, payroll staff may confirm payslips through the normal
workflow if they want a finalized payroll record. Confirmed slips are excluded
by the Draft filter: select **Done** or **All Except Rejected** when exporting
them. Daily attendance review is a separate process; this report default does
not implement a day-level attendance lock. Existing wizard records keep their
saved filters; newly opened reports default to Draft.

Bulk confirmation is available after upgrading `custom_hr_payroll` to
**18.0.4.16.0**: select computed Draft/Waiting records in Employee Payslips and
choose **Actions > Confirm Payslips**. Review the selected records and total Net,
then **Confirm Selected Payslips**. Standard confirmation is used; if salary
amounts have changed or any record fails, the selection is rolled back. See the
[bulk confirmation guide](../custom_hr_payroll/README.md).

For this default change, upgrade **hr_payslip_excel_report to 18.0.4.15.0** and
restart Odoo. No payslip status, salary line, attendance or approval is changed.
Validation: **56 payroll-report tests** passed, including standard batch generation
and export using the default filter without confirming or marking payment. The
installed browser verified Draft on the initial Summary and after switching to
Payroll Review, and both downloads passed. Done/All remain selectable.

The standard Generate Payslips action does not have the removed automation's
idempotent reuse: inspect existing slips before generating again to avoid
creating duplicates. Use Compute Sheet on existing drafts for updates instead.

## Deployment

Restart Odoo, upgrade **custom_hr_payroll to 18.0.4.12.0**,
**bambus_hr_attendance_ot_fine to 18.0.3.28.0**, and
**hr_payslip_excel_report to 18.0.4.12.0**, and reload the web
client. An upgrade migration removes only the withdrawn preparation menu, action,
views and access entry before report views are reloaded. Existing batches,
payslips, salary lines and payment information are not deleted or recomputed.
PDF/layout revisions are not part of this rollback; Excel remains available.

## Verification

Run the existing payroll-report and attendance test suites on an isolated DB.
The rollback regression checks cover the original generator, computed Draft
reporting and absence of the withdrawn UI. The installed-browser report check is:

```sh
python hr_payslip_excel_report/tests/browser/verify_report_wizard.py \
  --url http://localhost:8071 --db <test_database> --output /tmp/payroll-review.xlsx
```

Verified on 20 October 2026: **175 Odoo tests passed**. An upgrade from the
withdrawn 18.0.4.10.0 version preserved existing batch ownership, draft/finalized
payslip statuses and exact salary-line IDs/amounts, and removed the preparation
UI. Installed Chromium checks confirmed the standard batch button, absence of
the withdrawn shortcuts, Payslip Summary defaults and both existing Excel exports.
The stored batch-company field is retained for compatibility; it exposes no new
preparation actions. Production deployment remains separate from these tests.

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

Hourly correction verification: **183 Odoo tests passed**, including eight new
regressions for existing-draft refresh, attendance-date counts, second precision,
daily caps, local boundaries, custom rows and saved salary protection. The
controlled reference replay matched fresh generation after existing-draft edits;
source daily attendance and customer configuration are still required for full
client reconciliation. See the release readiness notes for assumptions.

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

Restored-staging verification: **188 Odoo tests passed**. Both Excel downloads
and Monthly/Daily/Hourly saved header totals passed installed Chromium checks.
The backup upgrade retained all saved salary lines and payslip states; a rolled-
back 23-draft recomputation reconciled header/report amounts with Net. Full
restored theme/SaaS UI parity and client acceptance remain separate.

```sh
python hr_payslip_excel_report/tests/browser/verify_wage_type_totals.py \
  --url http://localhost:8071 --db <test_database>
```

## Reviewed exception day pay

See [the coordinated upgrade and manual test guide](../bambus_hr_daily_ops/docs/REVIEWED_EXCEPTION_DAY_PAY.md).
The opt-in Monthly/Daily policy preserves raw attendance, uses saved reviewed
intervals for day classification, and retains saved fine amounts. Payroll exports
append reviewed hours separately from actual work. Recompute existing drafts;
exports do not calculate salary. Threshold tolerance is outside this change.

## Partial attendance salary treatment

Templates now offer **Use Half/Full-Day Thresholds** (existing behaviour) or
**Normal Day Pay Minus Approved Fines** for Monthly/Daily regular working dates.
The latter gives normal attendance-day pay for completed positive scheduled work
and deducts only saved approved fines, including a missing session. Actual work
hours, Hourly calculations, paid special-day policies and explicit leave remain
separate. Recompute existing drafts after selecting the option.

See [configuration, upgrade versions and expected payslip amounts](../bambus_hr_daily_ops/docs/PARTIAL_ATTENDANCE_SALARY.md).

## Withheld worked dates and Payable Days

Upgrade `bambus_hr_attendance_ot_fine` to **18.0.3.32.0**, then Compute Sheet on
existing draft/verification payslips. Generated WEEKEND/HOLIDAYS rows retain work
hours but exclude the Monthly withheld normal-day fractions. Both workbooks read
these saved rows for Payable Days; Present/Week-off Worked/Holiday Worked retain
their attendance classifications, including withheld work. Saved salary and
approved OT/fines retain their amounts. Finalized slips are not refreshed, and
exports do not recompute payroll. See the
[reconciliation and manual check](../bambus_hr_daily_ops/docs/WITHHELD_PAYABLE_DAYS.md).

## Empty-selection warning — 18.0.4.18.0

Download Excel validates Payslip Summary selection before returning the download
URL. If no payslips match, Odoo shows a warning in the existing client: generate
payslips from Payroll > Payslip Batches, or correct the company, period, employees,
department and status. Confirmed payslips require Done or All Except Rejected.
No file is requested and the wizard remains available to correct the filters.

The controller still validates direct/stale download URLs. Valid exports retain
the existing saved-salary rules and do not compute, confirm or modify payslips.
Payroll Review intentionally supports employees without payslips so it can list
missing-payroll exceptions. If no employees or payslips match, it also warns before
navigation. Upgrade hr_payslip_excel_report and restart Odoo to apply this change.

Validation: 59 payroll-report tests passed; installed Chromium verified the empty
Summary warning without a download/new page and both normal workbook downloads.
No customer deployment was performed.
