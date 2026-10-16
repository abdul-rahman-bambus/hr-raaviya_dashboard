# Attendance and payroll go-live readiness

Target: **Monday 19 October 2026**, client timezone Asia/Kolkata.
Review date: **16 October 2026**. Production deployment and client sign-off are
not established by the local test results recorded here.

## Status

The label/documentation change preserves existing policies and eligibility.
Paid Weekly Offs defaults enabled; Paid Public Holidays defaults disabled.
Both remain Monthly-contract features. Weekly Off Policy is still required to
control additional work earnings independently of normal paid-day credit.

**Do not consider the complete dashboard-to-payroll flow ready for live use yet.**
The manual-time-entry gap below remains open. No production settings or payroll
records were changed as part of this readiness review.

## Open items before live use

| Priority | Item | Evidence / required acceptance |
| --- | --- | --- |
| Blocker for dashboard-only entry | Manual check-in/check-out does not feed actual punch detection | `update_dashboard_attendance` writes the daily sheet/audit, not `hr.attendance`, and does not call recomputation. This matches the reported Present=1, Punched In/Out=0 and zero fine after editing times. Implement and test punch synchronization, or explicitly use and validate the existing actual-punch management workflow instead. |
| Payroll decision | Fixed 30-day denominator versus whole-month contract wage | Monthly day rate is wage / 30 and daily regular pay is summed without a monthly-wage cap. An isolated 31-day July fixture with a 12,000 Monthly contract, all 27 regular days worked and four paid weekly offs produced 12,400 regular pay. The fixture was rolled back. Confirm expected 28/29/30/31-day, joiner/leaver and unpaid-absence outcomes; the current sum is not capped at contract wage. |
| Client verification | NET rounding | The supplied screenshot shows Gross 3,862.29 and Fine 8.08, whose difference is 3,854.21, but displayed NET is 3,854.00. Inspect the deployed NET rule and currency rounding; repository default NET is BASIC + ALW + DED and does not explain an explicit whole-unit rounding rule. |
| Client configuration | Meaning of special-day multipliers | Normal paid-day credit plus additional 2x pay produces 3x total for a full day. If the client means double total pay, use additional 1x with normal credit. Confirm weekly-off and public-holiday settings separately. |
| Client acceptance | Actual employee setup | Confirm in-scope employee contracts, wage types, calendar timezone/work periods, effective employee/company templates, selected weekly offs, public-holiday dates and salary structure BASIC/OT/PH/fine rules. Screenshots included employees without schedules/contracts; identify whether these are test or in-scope records. |

The dashboard gap can also affect payroll attendance hours and day classification,
not just late fines. A UI time or HR audit log alone is not evidence of a real punch.
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

## Validation evidence

- Current label/documentation candidate, 16 October: **157 Odoo tests passed**
  with zero failures/errors, covering custom payroll, daily operations,
  attendance reports and payroll reports.
- Current candidate: **8 production OWL Chromium tests passed**.
- Installed-browser checks verified combined-review scrolling/deletion/approval,
  paid-off policy settings, normal day credit and worked-day refresh.
- Installed label verification confirmed both field labels omit “(Monthly)”,
  the weekly-off checkbox remains enabled by default, the public-holiday
  checkbox remains disabled by default, and both preserve the paid-day behavior.
- Isolated, rolled-back month-basis check confirmed 12,400 regular pay from a
  12,000 contract across 31 eligible paid dates; this remains an open client decision.
- None of these tests verifies the client production database, its NET rule,
  monthly salary-basis acceptance or the missing manual-dashboard punch path.

## Deployment and client acceptance sequence

1. Back up the live database/filestore and validate restore/rollback steps in the
   client's deployment environment before the planned rollout.
2. Install the approved release, restart Odoo to load the Python field labels,
   and upgrade affected modules. For this label change, upgrade
   `bambus_hr_attendance_ot_fine` to `18.0.3.25.0` and `bambus_hr_daily_ops`
   to `18.0.1.80.0`.
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
