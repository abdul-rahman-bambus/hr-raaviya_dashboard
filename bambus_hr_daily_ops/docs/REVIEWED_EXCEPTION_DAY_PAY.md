# Reviewed exceptions and half-day leave

## Enable the policy

Upgrade and restart these modules together:

| Module | Version |
| --- | --- |
| custom_hr_payroll | 18.0.4.14.0 |
| bambus_hr_attendance_ot_fine | 18.0.3.30.0 |
| bambus_hr_daily_ops | 18.0.1.85.0 |
| attendance_custom_report | 18.0.1.9.0 |
| hr_payslip_excel_report | 18.0.4.14.0 |

Under **Automation Rules > Late & Early Exit**, set **Day Pay for Reviewed
Attendance Exceptions** to **Regularize Reviewed Exception Time** on the intended
Monthly/Daily template. Existing templates default to **Use Actual Worked Hours**.
Employee/company template precedence and effective dates still apply. Hourly
contracts continue to use actual/HR-approved payable hours and their own caps.

Enable the late, early-exit and break rules for exceptions HR needs to review.
The new policy separates the first and second scheduled session's late entry,
early exit and internal gaps. It does not create exceptions for a completely
missing session. Use Half Day Leave for an explicitly absent half.

## What an HR decision does

| Decision | Day-pay classification with this option enabled | Fine |
| --- | --- | --- |
| Not reviewed, or Cancel | Actual worked hours only | No pending fine deduction |
| Delete / Ignore, then Approve Remaining Items | Actual hours plus that exception's saved missing scheduled interval | Zero for the ignored component |
| Keep item, edit minutes/method and approve | Actual hours plus that exception's saved missing scheduled interval | Saved amount from selected method and final fine minutes |
| Entire half absent, no exception decision | No invented work credit | Use explicit leave/absence treatment |

The system never changes check-in/check-out. Actual worked hours remain actual.
The reviewed interval is saved separately with the HR decision and audit. Editing
fine minutes changes the charge, not the interval that can be excused. Morning
arrival grace affects fine minutes; explicit review covers the corresponding raw
missing interval including grace. Unreviewed within-grace seconds/minutes still
follow actual-hours classification. **No new threshold tolerance is included.**

Only still-missing time inside the assigned work periods counts, once. Leave
intervals, public holidays, weekly offs, invalid contracts, open punches and full
absence do not acquire regularization credit. A later punch edit cannot expand
an old saved interval. Changed punches/schedule invalidate an open review; reopen
it before approving. Old aggregate approvals keep their saved money and receive
no guessed session credit. Enabling this option does not backfill old approvals
or create a second set of fines for them. To reassess an old date, reopen its
review and select **Review Session Exceptions**. This presents fresh session
proposals with a warning showing the previous fine amount. Cancel retains the
old approval; approving explicitly replaces it and saves both the previous
fine decision/amount and the new decisions in the audit. This is the path to
regularizing an already-reviewed date without silently repricing it.

After the last OT/fine approval for the selected date, the dashboard clears its
review filter and returns to the normal daily list. This also applies when
approval was opened from the broader **Late / Fine** or **Overtime** filter. If another type still has pending items, it switches to that review
filter. The selected date stays the same. A **Daily Attendance** button beside
the date and History controls also clears the current filter/search and returns to all
staff for that date, without changing approvals or reloading payroll.

## Explicit half-day leave

Click **Half Day Leave** to open confirmation. No leave is created by the click
alone, and attendance never creates leave automatically.

- Completed first-session punches only: suggest second-half leave.
- Completed second-session punches only: suggest first-half leave.
- Both sessions, no punches, an open punch or no clear split: HR chooses the half.
- HR selects the configured paid/unpaid Time Off type and confirms the request.
- Normal Time Off approval applies; only validated paid leave contributes paid
  leave credit to payroll. Unpaid leave does not contribute normal salary credit.
- An existing non-cancelled/non-refused request opens for review rather than
  creating another one. **View Half Day Leave** opens that request; cancellation
  remains an explicit Time Off/status-revocation action.

Payroll retains actual worked-day equivalents and adds eligible approved paid
leave separately. For four actual hours on an eight-hour day, approved paid
half-day leave produces one day's normal pay; unpaid half-day leave produces
half a day's normal pay. Pending paid leave does not create paid leave credit.

## Verify with three employees

Use a test database. Set Monday's schedule to 09:45–14:00 and 14:45–18:45,
Asia/Kolkata. Monthly 8,000; Daily 885; Hourly 53. Contracts must cover the date.
Use 26 October 2026 and zero seconds in these entries:

| Entry | Check in | Check out |
| --- | --- | --- |
| Morning | 10:00 | 14:00 |
| Afternoon | 14:45 | 18:15 |

Actual work is 7:30. With 5-minute morning grace, expect a 10-minute morning
late proposal and a 30-minute afternoon early-exit proposal. Use **Per Minute
from Daily Salary**. Compute draft payslips before approval: Monthly/Daily day
classification is half a day; Hourly pay is 7.5 × 53 = 397.50.

Ignore the morning cab delay, retain the afternoon fine, then approve remaining
items. Recompute the same drafts:

| Wage type | Normal pay | Fine | Net with no other rules |
| --- | --- | --- | --- |
| Monthly 8,000 | 8,000 / 31 = 258.06 | (8,000 / 31) × 30 / 495 = 15.64 | 242.42 |
| Daily 885 | 885.00 | 885 × 30 / 495 = 53.64 | 831.36 |
| Hourly 53 | 397.50 | 0 | 397.50 |

Monthly/Daily classification is one day after review. Actual work stays 7:30;
reviewed exception time is 0:45. Ignore both components on a separate date:
normal day pay remains, fine becomes zero. Change fine minutes on another date:
the charge changes without inventing additional work or filling an absent half.

On a fresh working date enter only the morning session. Click Half Day Leave,
verify second half is suggested, and Cancel: no request exists. Repeat and select
unpaid leave: after confirmation/approval normal pay remains half a day. On a
separate employee/date select paid leave: it contributes the other half only
when approved under that Time Off type's workflow.

## Payroll and exports

Run **Compute Sheet** on the existing draft after review/leave changes, then
export Payroll Review and Payslip Summary with Draft included. Exports do not
recompute salary. Finalized salary/detail rows are not rewritten by Compute Sheet.

Payroll and attendance reports share the reviewed-time classification helper.
Payroll Review (Register and Daily Detail) and all wage summary sheets append
**Reviewed Exception Hours**, separately from actual hours. These attendance
columns describe current policy/review records; money remains saved salary data.
Split non-overlapping periods sum reviewed hours; overlapping periods remain
flagged rather than double-counted.

Earnings/deduction detail displays the effective saved rate with its unit:
per hour for salary multipliers/fixed hourly pay, per minute for salary-minute
fines, or amount for a fixed/half/full-day charge. Mixed fine methods stay in
separate detail rows. Derived rates have six decimal places; amounts retain
currency rounding. Saved approvals are not repriced from a changed contract.
The existing OT salary-hour divisor is unchanged by this release.

## Validation for this candidate

22 October 2026, isolated `raaviya_attendance_test` database:

- 204 Odoo regression tests passed, zero failures/errors; the final focused
  reviewed-exception suite also passed all 37 cases.
- 14 production OWL Chromium tests passed.
- Installed-browser verification passed for Monthly/Daily/Hourly pay, independent
  half/session review, final-approval navigation, rate units, both XLSX exports,
  legacy session reassessment/Cancel/audit, and missing-half confirmation/Cancel.
- The existing installed combined-review check passed, including native list-row
  deletion, approval and scrolling at five viewport sizes.

Run the installed check with:

```sh
python bambus_hr_daily_ops/tests/browser/verify_reviewed_day_pay.py \
  --url http://localhost:8071 --db <test_database>
```

These checks establish local behavior for the candidate, not production rollout
or customer acceptance. The separate threshold tolerance and dashboard-only
punch synchronization work remain open.
