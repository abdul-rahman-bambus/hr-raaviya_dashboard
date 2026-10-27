# Attendance and payroll go-live readiness

Original target: **Monday 19 October 2026**, client timezone Asia/Kolkata.
Latest review: **27 October 2026**. Production deployment and client sign-off are
not established by the local test results recorded here.

## Status

The calendar-month salary change preserves existing paid-off policies and eligibility.
Paid Weekly Offs defaults enabled; Paid Public Holidays defaults disabled.
Both remain Monthly-contract features.
HR can now withhold/restore an individual paid date with a reason and audit history;
unworked dates show an unpaid status, while worked dates retain attendance and a
withheld indicator. Recompute draft payroll; finalized salary lines remain saved. Weekly Off Policy is still required to
control additional work earnings independently of normal paid-day credit.

The dashboard manual-entry gap is resolved in the independent-attendance release
below. Local validation passed; production rollout still requires a backed-up
staging upgrade and customer configuration/acceptance checks. No production
settings or payroll records were changed by this work.

## Remaining items and resolved salary decision

| Priority | Item | Evidence / required acceptance |
| --- | --- | --- |
| Resolved locally; deployment pending | Dashboard time edits feed actual punches | Daily Ops 18.0.1.92.0 creates/updates `hr.attendance`, preserves split sessions and invokes detection. All three wage types, payroll and exports were tested without History models. See the coordinated migration below. |
| Implemented; deployment acceptance pending | Calendar-month salary basis | Client selected actual calendar days on 20 October. Monthly rates now divide wage by the attendance month's 28/29/30/31 days through a shared contract helper. Full eligible months produce the contract wage; partial and cross-month periods use each date's full calendar-month divisor. The former July 12,400 result on a 12,000 contract is historical evidence of the replaced flat-30 basis, not current behavior. Validate the deployed release and recompute draft payslips. |
| Client verification | NET rounding | The supplied screenshot shows Gross 3,862.29 and Fine 8.08, whose difference is 3,854.21, but displayed NET is 3,854.00. Inspect the deployed NET rule and currency rounding; repository default NET is BASIC + ALW + DED and does not explain an explicit whole-unit rounding rule. |
| Client configuration | Meaning of special-day multipliers | Normal paid-day credit plus additional 2x pay produces 3x total for a full day. If the client means double total pay, use additional 1x with normal credit. Confirm weekly-off and public-holiday settings separately. |
| Client acceptance | Actual employee setup | Confirm in-scope employee contracts, wage types, calendar timezone/work periods, effective employee/company templates, selected weekly offs, public-holiday dates and salary structure BASIC/OT/PH/fine rules. Screenshots included employees without schedules/contracts; identify whether these are test or in-scope records. |

Legacy manual-only snapshots can affect payroll attendance and day classification.
The migration blocks audited manual times without actual punches for review.
A UI time or HR audit log alone is not evidence of a real punch.
Pending and ignored adjustments must not silently become salary amounts.

## Delivered behavior to verify with client examples

| Scenario | Expected result |
| --- | --- |
| Paid weekly off, no punches | One normal paid-day credit per eligible date; no leave balance change |
| Paid public holiday, no punches | Same credit only when Paid Public Holidays is enabled |
| Worked paid special day | Normal day credit remains; actual hours determine worked-day fraction; additional pay follows the work policy and HR approval |
| Public holiday overlaps weekly off | One normal day credit, classified under public holiday |
| Actual hours cross half/full-day threshold | Worked-day fraction updates; fixed targets are not capped at shorter schedule hours |
| Compute Sheet after changes | Generated worked-day rows and draft salary refresh; custom unrelated day codes remain |
| Delete / Ignore then Approve Remaining Items | Exclusion is saved; excluded item stays out of payroll/recalculation |
| Delete / Ignore then Cancel | No exclusion is saved |
| Pending OT or fine with an effective template | Proposal visible for review; amount does not affect payroll until approved |
| Daily or Hourly contract | No new automatic paid-off credit despite the shortened labels |
| Actual arrival 09:55, shift start 09:45, grace 5 minutes | Five chargeable late minutes proposed, subject to the applicable rule and HR review |

Check both base/payable days and earnings. Do not sum full paid-day credit and
worked-day fractions twice. Hour fields in the dashboard use HH:MM; worked-day
input tables may display decimal hours.

## Independent attendance decisions — 27 October 2026

Deploy Daily Ops **18.0.1.92.0**, Attendance OT/Fine **18.0.3.34.0**,
Attendance Report **18.0.1.12.0** and Payslip Excel Report **18.0.4.19.0**
together. [Migration instructions](INDEPENDENT_ATTENDANCE_DECISIONS.md) describe
backup, transactional guards and preserved raw archives. History models, actions,
menus, dashboard buttons and creation cron are removed. Current punches/Time Off
and independent employee/date/company HR decisions feed dashboard/payroll/reports.

Validation passed: **254 Odoo tests**, **17 production OWL Chromium tests**,
all installed attendance/payroll/report browser scenarios, and **6 independent
acceptance tests on a fresh database with no History tables**. Migration retained
fixture decision IDs, approvals/exclusions/coverage, hourly corrections and all
finalized salary amounts/states. Manual-only snapshots stopped the upgrade and
rolled back; verified real punches then allowed the upgrade. Duplicate,
incomplete and conflicting-table guards plus idempotent retry checks passed.

The final backend suite had no WARNING/ERROR entries. Browser runs included
handled concurrent-transaction retries and expected empty-report warnings; all
assertions passed. Production load/concurrency and the customer's migration data
still require staging validation. Attendance report wizard access is explicitly
internal-user only; portal denial and internal creation were tested.

Seconds/tolerance behavior and salary policies are unchanged. The evidence below
records earlier releases; their manual-only snapshot fallback is superseded.

## Historical validation evidence

- Calendar-month candidate, 20 October: **173 Odoo tests passed**
  with zero failures/errors, covering custom payroll, daily operations,
  attendance reports and payroll reports.
- Current candidate: **10 production OWL Chromium tests passed**.
- Installed dashboard check confirmed Paid Weekly Off on Sunday 18 October,
  Paid Public Holiday on Monday 19 October, and Not Marked after disabling holiday
  payment. Labels use payroll eligibility and do not create attendance or leave.
- Installed withholding check verified Cancel, required reasons, immediate unpaid
  status, persistence across reload, audit Logs, draft payroll totals, restoration
  under changed policy, and preservation of worked attendance.
- Installed October check confirmed a 9,000 Monthly contract gives 9,000 / 31
  normal credit per eligible special date; payable days stay one as worked-day
  fractions refresh from 0.5 to 1.
- Installed-browser checks verified combined-review scrolling/deletion/approval,
  paid-off policy settings, normal day credit and worked-day refresh.
- Installed label verification confirmed both field labels omit “(Monthly)”,
  the weekly-off checkbox remains enabled by default, the public-holiday
  checkbox remains disabled by default, and both preserve the paid-day behavior.
- Historical isolated, rolled-back flat-30 check produced 12,400 regular pay from a
  12,000 contract over 31 eligible dates. The client has now selected calendar-month
  days; new regression coverage verifies full months, partial contracts,
  cross-month periods, absence/leave, paid special days, local-date boundaries,
  salary-derived reviews and preservation of approved snapshots/final salary lines.
- None of these tests verifies the client production database, its NET rule,
  deployed salary reconciliation or the missing manual-dashboard punch path.

## Deployment and client acceptance sequence

1. Back up the live database/filestore and validate restore/rollback steps in the
   client's deployment environment before the planned rollout.
2. Install the approved release, restart Odoo to load the salary-rate changes,
   and upgrade affected modules. For the calendar-month salary rule, upgrade
   `custom_hr_payroll` to `18.0.4.11.0`, `bambus_hr_attendance_ot_fine` to
   `18.0.3.26.0` and `bambus_hr_daily_ops` to `18.0.1.81.0`.
   For the earlier attendance/payroll changes also upgrade `custom_hr_payroll`,
   `attendance_custom_report`, and `hr_payslip_excel_report` where installed.
3. Reload the browser and confirm the two shortened labels and their tooltips.
   Confirm that Monthly eligibility and saved checkbox values remain unchanged.
4. Confirm client templates and rates using the scenarios above in a test copy.
   Enable Paid Public Holidays for this client explicitly if that is intended.
5. Resolve the open items, then reconcile a sample Monthly, Daily and Hourly
   employee from actual punches through reviews, draft salary and exported reports.
   Include an absent day, a missed punch, approved/excluded fines and special days.
6. Recompute draft payslips after approved changes. Do not assume finalized salary
   lines have been refreshed automatically. Obtain client payroll acceptance of
   base salary, additional earnings, deductions, rounding and final net amounts.

No scheduled automation, live deployment or financial approval is created by
this document. The target date is a plan, not a deployment confirmation.

## Preparation rollback

The client chose the existing Payslip Batches > Generate Payslips workflow and
Payslip Summary with Draft included. The separate preparation wizard and its
batch/report shortcuts have been withdrawn. Upgrade `hr_payslip_excel_report`
to `18.0.4.11.0` and reload the client. The migration removes only the withdrawn
UI/access records, retaining existing payroll data and the earlier attendance,
paid-day withholding and calendar-month calculation changes. Recompute draft
salary after attendance/approval changes; Excel exports read saved salary lines.
The standard generator can create duplicates if rerun, so inspect existing slips
and use Compute Sheet for corrections. No production deployment is implied.

Rollback validation: **175 Odoo tests passed**. The isolated upgrade preserved
existing batch company, draft/finalized statuses and salary lines; installed UI
checks confirmed withdrawn buttons/menu are absent and both standard report
exports still work. The stored batch-company field is retained for compatibility.

## Hourly refresh correction (20 October 2026)

Existing draft/verification payslips now refresh stored hourly hours/days before
statistics, work rows and salary. Hourly Present/Payable Days count completed,
positive attendance dates instead of scheduled days or threshold fractions.
Multiple punches count once per local check-in date; daily caps and raw punches
are preserved. Export continues to read saved salary; recompute drafts after edits.
Finalized/cancelled slips are skipped. Monthly/Daily behavior remains covered.

Upgrade `custom_hr_payroll` to `18.0.4.12.0`,
`bambus_hr_attendance_ot_fine` to `18.0.3.28.0`, and
`hr_payslip_excel_report` to `18.0.4.12.0`, then recompute affected drafts.
Do not regenerate duplicate slips. **183 Odoo tests passed**, zero failures/errors,
including eight new hourly regression cases.

A rolled-back 17-employee September reference reconstruction verified existing
draft recomputation agrees with fresh standard generation. Hourly day counts
match 23/24/18/23. With displayed decimal hours the net is 222,278.82; an inferred
nearest-minute interpretation matches all 17 source nets and the 222,279.36 total.
This is not validation of original daily attendance: Monthly/Daily day patterns
were reconstructed and OT/fine amounts imported as saved approvals. Source
punches, rate/grace rules and customer configuration still need reconciliation.
No production deployment or client acceptance is implied. The manual-dashboard
punch/detection gap described above remains open.

## Restored staging correction: 21 October 2026

The supplied backup was restored with its filestore to an isolated test database
and neutralized before application use. Scheduled jobs, incoming/outgoing mail
servers and payment providers were disabled; queued outgoing email was cancelled
on the copy. No production data was changed and the source ZIP was retained.

The backup contains older custom payroll module metadata alongside newer
attendance/report modules. Current templates also differ from the earlier saved
draft salary configuration. Treat module upgrade, rule repair and explicit
draft recomputation as separate operations.

Implemented: wage-specific BASIC category headers from saved totals; supported
Daily/Monthly/Hourly base-code adaptation with retained legacy fallback; report
deduction sign normalization for both saved NET conventions; and nonoverlapping
Other Allowances. Upgrade custom_hr_payroll 18.0.4.13.0,
bambus_hr_attendance_ot_fine 18.0.3.29.0 and hr_payslip_excel_report 18.0.4.13.0.

Validation: **188 Odoo tests passed**, zero failures/errors. Installed Chromium
checks passed for all three wage-specific header totals and both Excel exports.
The restored upgrade retained all **138 salary lines and 26 payslip states/batch
links**. A separate rolled-back recomputation checked all 23 selected drafts: saved
Basic/header/report values and Gross minus deductions reconciled with Net.
The three-wage baseline and corrections/switch checks are covered by regression
tests; see [manual acceptance](MANUAL_PAYROLL_TEST.md) for client execution.

Full restored-server UI parity is not established: seven installed theme/SaaS
add-on sources are absent locally (bambus_saas_client, debranding and five
muk_web modules). Payroll backend tests ran with available payroll sources; the
installed Chromium checks used the complete isolated payroll test installation.
No fake add-on replacements were installed.

Remaining acceptance: correct multi-day/open punches through HR, review manual
Present overrides and pending adjustments, and execute the client manual cases.
Dashboard time editing still does not create/update actual punch records; that
separate documented blocker remains open. No deployment or cash-payment approval
is implied by these results.

## Reviewed exception candidate (22 October)

See [the reviewed exception guide](REVIEWED_EXCEPTION_DAY_PAY.md). The new
Monthly/Daily option defaults off; HR-reviewed intervals can restore day pay
without changing punches. Explicit half-day confirmation, approval navigation,
saved-rate units and report reviewed-hour columns are included. Threshold
seconds/tolerance and the dashboard-only punch-entry gap remain separate open
items. Existing aggregate approvals are not backfilled with guessed intervals.
Production deployment and client acceptance are still pending.

Candidate evidence: 204 backend tests, 14 production OWL Chromium tests, final
37-case reviewed-exception suite, and installed checks for three wages, native
combined review, legacy reassessment/audit, half-day confirmation and both XLSX
exports passed. No production deployment is established by these checks.

## Normal day pay minus approved fines

The opt-in [partial-attendance policy](PARTIAL_ATTENDANCE_SALARY.md) addresses the
customer's attended-day normal-pay minus missing-time fines workflow, including
whole missing sessions. Existing thresholds remain the default. Deployment must
include the four coordinated module upgrades, explicit template selection and
draft recomputation. Threshold tolerance and dashboard-only punch synchronization
remain separate; this candidate does not establish production acceptance.

Local evidence: **224 Odoo tests**, **16 production OWL Chromium tests**, and
sequential installed-browser checks for both salary modes passed. The new mode
verified six-hour dashboard/review proposals, Monthly/Daily/Hourly payslip totals
and both XLSX downloads; the existing reviewed-interval workflow passed too.

## Worked withheld special-day count correction (23 October)

Upgrade `bambus_hr_attendance_ot_fine` to **18.0.3.32.0** and recompute existing
draft/verification payslips. Withheld Monthly work no longer adds a normal paid
day through WEEKEND/HOLIDAYS rows or the standard calendar fallback. Actual work
statistics/hours and approved earnings/fines remain; finalized rows stay saved.
The supplied October reproduction now reports **11 Payable Days** with unchanged
Basic 2,838.71, OT 773.75, Fine 294.55 and Net 3,317.91. **228 Odoo tests** and the
installed dashboard/both-XLSX-download check passed. Seconds tolerance, production
deployment and client acceptance remain separate. See
[the upgrade/manual guide](WITHHELD_PAYABLE_DAYS.md).


## Daily-card pencil navigation (26 October)

`bambus_hr_daily_ops` **18.0.1.87.0** adds a pencil beside each employee name on
Daily Attendance. It opens actual attendance entries filtered by employee and
selected local check-in date under existing attendance access rules. Empty dates
open an empty native list; Logs retains time/audit history. Upgrade/reload assets.

Validation: **15 backend navigation/asset tests**, **17 production OWL Chromium
tests**, and installed Monthly/Daily/Hourly and empty-day navigation checks passed.
No attendance, approval or salary data is changed by opening this list. The
separate manual dashboard punch synchronization and seconds-tolerance gaps remain.
These checks do not establish production deployment.


## Bulk confirmation of reviewed payroll (26 October)

`custom_hr_payroll` **18.0.4.16.0** adds Employee Payslips > Actions > Confirm
Payslips with a count/Net/selection dialog. Standard per-slip confirmation runs;
invalid selections, changed salary-rule amounts at currency precision, or any
confirmation error prevent completion and roll back the selection. Done reporting
requires Done/All Except Rejected rather than the new Draft report default.
No existing slips are confirmed on upgrade and no salary payment is initiated.

**237 Odoo tests** and installed native-list/Cancel/three-wage/Done-report checks
passed on an isolated test database. Standard accounting/loan hooks remain in
place; their target configuration still requires normal deployment validation.
Production deployment/client confirmation remain separate. See
[the bulk confirmation guide](../../custom_hr_payroll/README.md).


## Runtime warning cleanup (26 October)

See [the source fixes and seven coordinated upgrade versions](RUNTIME_WARNINGS.md).
Deprecated company/precision/string APIs, missing-field constraints, duplicate
labels, report/license metadata, icon/alert semantics and old payroll kanban
names were corrected. Eager report test imports causing normal startup errors
were removed without losing test discovery. The invalid approved-fine/raw-split
equality diagnostic was removed; raw figures and approved amounts remain intact.
No warning filters or salary policies were changed.

Final local validation: **237 tests**, zero warnings/errors on upgrade/test logs,
and clean fresh normal HTTP/browser logs. All four native payroll cards and both
Excel exports passed, retaining exact decimal salary. Deployment and any warnings
unique to the client's local installation still require that installation's check.


## Additional local-log warnings (26 October)

The client log exposed Employee Info/Loan/Salary Advance warnings outside the
previous payroll-only registry and Markdown fallback-description parsing errors.
See [the follow-up source fixes and upgrade list](ADDITIONAL_RUNTIME_WARNINGS.md).
The SaaS client is explicitly excluded and left unchanged.

Expanded validation with 85 modules passed **243 tests**. Coordinated upgrade/test
and fresh normal HTTP/sequential browser logs had zero warnings/errors. Family,
loan and advance forms, list-create sequences, advance status, three Apps
descriptions and both payroll downloads passed. Client-local modules beyond that
registry and the deliberately excluded SaaS messages are not claimed fixed.

## Attendance classification placement — Daily Ops 18.0.1.90.0

Attendance Day Classification moved from Overtime to Late & Early Exit, directly
below Day Pay. Fields, visibility conditions, stored values and calculations are
unchanged. Upgrade Daily Ops and reload the client. Isolated test validation:
12 targeted TestBackendAssets tests passed with zero failures/errors; installed
Chromium check confirmed both tab placement and schedule/fixed field visibility,
with half-day/full-day values retained. Test and runtime logs contained no
warnings/errors. This evidence does not establish customer deployment.

## Dashboard refresh after actual punch corrections — 18.0.1.91.0

When actual punches exist for the selected employee/local date, Daily Attendance
shows their earliest check-in, latest available checkout and summed worked hours.
A saved daily-sheet snapshot no longer overrides those times. Unapproved hourly
pay preview follows current worked hours; explicitly approved hourly pay, manual
statuses, fine/OT approvals and exclusions remain saved HR decisions. Manual-only
dates without punches keep their existing snapshot fallback; this does not fix
the separate dashboard manual-time-to-punch synchronization gap.

After editing Punch Logs through the pencil, return to Daily Attendance (or reload
its selected date). Review/reassess any old fine approval explicitly: fixing punches
does not automatically cancel a previously approved deduction. Recompute draft
payslips before exporting; finalized payslips are not rewritten. Upgrade Daily Ops
and restart Odoo to apply the server fix.

Validation: reproduced the original 2.25 vs 8.25 stale snapshot for all three wage
types before the fix. Then 59 dashboard/unified-review Odoo tests passed with zero
failures/errors, including split-punch edits, removing a session, open checkout,
manual status preservation and unchanged saved fines. Installed Chromium verified
Monthly/Daily/Hourly pencil navigation and refreshed values after action-stack
return, with the selected date and approved fine amounts retained. No WARNING or
ERROR entries in the passing test/runtime logs. Customer deployment remains pending.

## Empty payroll Summary warning — report 18.0.4.18.0

Payslip Summary now validates its selected company, period and filters before
returning the download URL. An empty selection shows an Odoo warning explaining
how to generate payslips or correct filters (Done/All for confirmed slips), without
requesting a file or navigating to the controller's Bad Request page. Direct
stale download URLs retain server validation. Payroll Review still permits
missing-payslip exception reporting for matching employees; no matching employees
also produces a warning. Existing salary/export/approval behaviour is unchanged.

Validation: 59 payroll-report Odoo tests passed with zero failures/errors.
Installed Chromium verified the warning, no download request/new page, preserved
web client and wizard, and successful normal Payroll Review and Summary XLSX
exports. Expected UserError warning logging remains enabled. This does not
establish customer deployment. Upgrade hr_payslip_excel_report and restart Odoo.
