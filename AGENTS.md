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
- Dashboard paid-day statuses are derived using payroll eligibility helpers; only
  replace unmarked dates. Preserve actual punches, leave and explicit HR statuses.
  Exclude paid dates from Not Marked counts without marking them Present or creating
  punches/leaves. Keep derived status keys out of persisted sheet status values.
- Per-employee/date/type paid-day decisions live in append-only
  `bambus.attendance.paid.day.decision` history. Use the validated HR action with
  reason/company checks; never mutate history or infer withholding from Absent.
  Shared eligibility helpers exclude withheld credits in payroll and reports.
  Withheld Monthly special dates also bypass normal worked-hours fallback; retain
  actual work statistics and approved OT/fines. Restore reapplies current eligibility.
  Generated WEEKEND/HOLIDAYS days exclude withheld worked fractions; their hours
  remain actual work. Never let a withheld worked date re-enter Payable Days via
  a generated row or the default calendar fallback. Export saved day rows without
  silently recomputing salary; finalized rows and amounts remain snapshots.
  Use unpaid derived statuses only on otherwise unmarked dates, and show a separate
  withheld indicator on worked/manual/leave rows. Never persist derived status keys.
- Weekly Off Policy and Public Holiday Policy independently control additional
  work earnings. The paid-day booleans do not replace those policies. Weekly-off
  rates come from the Overtime tab; holidays have their own calculation/rate policy.
- Count an overlapping public holiday/weekly off once, using holiday precedence.
  Keep normal credit and approved extra pay separate. A 2x additional earning plus
  normal day credit can total 3x for a full special day.
- Detection is a proposal. With an effective template, unapproved extra pay/fines
  do not become payroll amounts. Preserve approved snapshots and saved exclusions;
  Ignore/Delete is persisted only by Approve Remaining Items. Cancel discards it.
- Compare actual daily worked hours to the effective day thresholds, except for
  the explicit opt-in reviewed-exception policy below. Do not cap
  classification hours at a shorter schedule and make a fixed full-day target
  unreachable. Reports and payroll must agree on day classification.
- Hourly payroll counts distinct local check-in dates with completed, positive
  actual punches, without half-day fractions. Sum punches per date before daily
  caps; retain raw attendance and precision. Compute Sheet explicitly refreshes
  stored hourly hours/days before statistics, generated work rows and salary.
  Report Payable Days is the saved count; Present Days reads current punches.
  Recompute existing drafts after punch changes; exports never recompute salary.
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

## Payroll workflow

Use standard Payslip Batches > Generate Payslips, then Payroll Reports > Payslip
Summary. Computed Draft payslips are valid report sources; users must include
Draft (or All Except Rejected) and recompute draft salary after attendance/review
changes. Exports do not compute salary, confirm payroll or record payment.
The separate Prepare Draft Payroll wizard from PR #121 was withdrawn at the
client's request. Do not reintroduce its menu, batch shortcuts or report handoff.
Preserve existing batches, salary lines and the Monthly/Hourly/Daily summary.

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

## Restored staging reconciliation

- BASIC is a salary category, not necessarily a rule code. Header aggregates
  must use saved line totals and include BASIC_MONTHLY/BASIC_DAILY/BASIC_HOURLY.
  Header repair must not rewrite salary lines, finalized states or batch links.
- The attendance upgrade adapts the supported wage-specific BASIC codes to the
  shared template regular-pay total, retaining their conditions and non-template
  fallback expression. Do not rewrite unrelated custom salary rules. Daily
  special-day attendance must not disappear merely because a legacy expression
  reads only DAYSWORKED. Paid unworked credits still apply only to Monthly.
- Reporting supports positive-DED/subtracting-NET and negative-DED/adding-NET
  using saved GROSS/NET reconciliation. Other Allowances excludes separately
  displayed OT and holiday/special-day earnings. Preserve refund signs.
- Template changes do not recalculate saved draft salaries. Compare current
  policy, HR statuses, attendance and saved salary separately; exporting does not
  approve or recompute payroll. Manual Present overrides can differ from actual
  worked-day equivalents used in normal pay. Do not silently remove overrides.
- Restore backups into a separate database containing test in its name, restore
  the filestore, neutralize before starting HTTP/cron, and preserve the source.
  Never commit customer dumps, exports, credentials or reconstructed fixtures.

## Reviewed exception day pay

- `reviewed_exception_day_pay` defaults to `actual`. The `regularize` option is
  Monthly/Daily only and uses effective date-specific templates. It adds saved,
  server-derived exception intervals for classification, never edited fine hours.
  Keep raw punches, actual hours and Hourly billable hours unchanged.
- Session late/early/internal-gap decisions are independent. An approved fine
  deducts its saved amount; ignored decisions deduct zero. Both can excuse only
  the corresponding saved missing schedule interval. No credit for complete
  missing sessions, leave, open punches, special dates or invalid contracts.
  Union intervals once; a subsequent punch change must not expand old coverage.
- Preserve legacy aggregate approval amounts without inventing session coverage
  or creating duplicate fine proposals. Never backfill approvals on upgrade.
  Review Session Exceptions explicitly proposes replacement fines; Cancel keeps
  the old decision, and approval audits the previous amount/data. Keep OT unchanged
  when reassessing fines only.
  Tolerance/seconds changes remain a separate, explicitly deferred task.
- Half Day Leave opens explicit confirmation: completed FN suggests AN, AN
  suggests FN, ambiguous cases require HR selection; choose paid/unpaid type.
  No automatic leave from punches; normal Time Off approval and duplicate/company
  checks apply. Existing leave opens rather than toggling/deleting silently.
- After saving reviews, use fresh date-wide pending states before clearing the
  review filter or moving to the other pending type. Keep the selected date.
- Payroll detail rates explain saved amounts, with per-hour/per-minute/amount
  units and separate rows for mixed methods. Do not reprice historical approvals.
  Report reviewed hours separately from actual hours and aggregate split periods
  without double-counting overlapping ranges. Recompute existing drafts explicitly.

- Attendance return navigation applies to both general fine/overtime filters and
  their pending-review variants. Approved hours can remain positive: determine
  completion from fresh pending flags, not from zero hours. The Daily Attendance
  button clears filter/search/page only, retaining the date and saved decisions.

## Configurable partial attendance salary

- `partial_attendance_salary_treatment` defaults to `thresholds`, preserving the
  existing threshold/reviewed-interval policy. The opt-in `fine_only` mode gives
  normal attendance-day credit once for positive completed work overlapping the
  assigned regular working periods. No threshold-based half-day cut in that mode.
- Fine-only mode overrides the earlier `reviewed_exception_day_pay` behaviour;
  never fabricate full worked/regularized hours to implement day pay. Shared day
  fractions must feed payroll, generated work rows, attendance and payroll reports.
- Include missing whole sessions in enabled late/early/internal-gap proposals on
  attended dates. Do not create leave, approve money automatically, generate an
  absence fine, or count only open/zero/outside-schedule punches as attended.
- Preserve Hourly pay, effective-template/contract/company boundaries, validated
  leave fractions, special-date credits/withholding and separately approved OT.
  No duplicate attendance credit for leave time. Keep saved fine snapshots even
  when a mode changes; do not append duplicate session/aggregate proposals.
- Recompute existing draft/verification payslips; the new day credit must reach
  DAYSWORKED days while retaining actual hours. Preserve finalized salary/details.
