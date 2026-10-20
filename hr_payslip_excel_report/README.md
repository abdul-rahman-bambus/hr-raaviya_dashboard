# Payroll reports: standard batch workflow

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
   period/employees and **Draft** (or **All Except Rejected**) status, then
   **Download Excel**. Payslips must fall entirely within the selected dates.

Payslip Summary contains **Monthly**, **Hourly**, **Daily** and **Final Summary**
sheets. Normal paid weekly-off/public-holiday credits follow the template rules;
approved additional holiday pay is shown separately. Payroll Review remains a
separate option for detailed attendance/approval checks and review exceptions.

Generating a batch does not confirm payslips or record cash payment. Keep the
actual Excel used for cash payment as the payment-period record. Only approved
adjustments are payable under effective templates. The separate manual-dashboard
punch/detection gap remains documented in the attendance module.

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
