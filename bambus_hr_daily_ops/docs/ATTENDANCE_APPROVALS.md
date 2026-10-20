# Attendance approvals and weekly-off pay

Open HRMS → Attendance → Attendance Editor. Either the OT or Fine control opens
one review containing every applicable item for that employee and local date:
OT, Late Fine, Break / Gap Fine and Early Exit Fine. Hourly Pay keeps its own
existing review; hourly contracts do not receive additional OT.

Adjust hours, calculation and notes, then choose **Approve Remaining Items**.
**Delete / Ignore** removes an item from this review. Approval saves its exclusion;
Cancel discards unsaved changes. In the native daily-sheet popup, remove a fine
with the list trash icon or select Ignore Overtime, then approve. Ignored items
remain excluded on attendance refresh, recalculation and reopening. Punches are
retained. Existing aggregate fine approvals are retained as one previously
combined fine instead of being split into guessed amounts.

Only approved attendance adjustments enter template-driven payroll. Detection
remains available for review but does not pay OT or deduct fines automatically.
Previously approved snapshots and ignored items survive daily-sheet refresh.
Stale reviews must be reopened before saving; only HR users in the selected
company can approve them.

## Pay rules

- Daily and Monthly holiday / weekly-off worked hours receive regular pay plus
  separately approved additional OT. With 8 hours, normal day pay 100 and
  calculation **1.5x Salary**, regular pay is 100 and OT is 150, total 250.
- Configure Weekly Off Policy as All Worked Hours and OT calculation as
  1.5x Salary for that example. Public Holiday Policy must allow all worked hours;
  its independent calculation defaults to 1.5x Salary on newly created templates.
  Existing configured template rates are preserved and HR can review them.
- Hourly contracts receive regular hourly pay, using the existing daily caps and
  approved payable-hour corrections, without an additional OT/holiday earning.
- For Monthly employees, **Paid Weekly Offs** credits one normal day
  on each configured weekly off, with or without attendance. It remains enabled
  by default. **Paid Public Holidays** provides the same normal credit
  for public holidays; it defaults to disabled to preserve existing payroll.
  Enable it on this client's effective template. No leave request is created
  and no leave balance is consumed. Daily/Hourly employees receive no automatic
  paid-off credit. Public-holiday classification wins on overlapping dates, so
  a date receives at most one normal day credit, within contract dates.
- Monthly day pay uses wage / calendar days in the local attendance date's month
  (28/29/30/31); Daily pay uses daily_wage. A paid Monthly
  special day retains its whole normal credit even when only part of the day
  is worked. Approved OT/holiday work is additional pay under its own policy.
  Without the paid-off policy, special-day normal pay retains the existing
  actual worked hours / calendar hours-per-day calculation.
- Worked-day fractions follow actual attendance hours and the template's
  half/full-day thresholds. Scheduled hours no longer cap the comparison and
  prevent reaching a higher fixed full-day target. Editing punches refreshes
  the attendance counters. **Compute Sheet** also rebuilds generated Worked Days
  & Inputs rows before salary evaluation, preserving unrelated custom codes.
  Paid credit rows top up worked fractions to a full paid day; they do not
  duplicate a day already included in WEEKEND/HOLIDAYS. Completed salary lines
  are not refreshed automatically.
- Payslip → Payables shows paid weekly-off and public-holiday days/amounts.
  Both amounts are included in Regular Pay Amount. Public Holiday Amount is
  the separate additional approved earning.

The standard BASIC salary rule uses the new regular-pay total for template-driven
Daily/Monthly payroll and existing billable hours for Hourly payroll. Legacy
Monthly payroll without an effective template retains contract wage. OT and PH
remain separate salary-rule inputs, each paid once. Verify that the employee's
salary structure includes the corresponding OT / PH rules; independent custom
BASIC rules must use total_regular_pay_amount to apply these same rules.

Reports recognize PAID_WEEKLY_OFF and PAID_PUBLIC_HOLIDAY credit rows.
Paid Weekly-off Days and Paid Public Holiday Days count normal paid credits,
including worked dates. Worked-day counts and additional approved earnings
remain separate. Payroll review daily rows explicitly identify worked paid-off
dates, and attendance Monthly Summary exposes both paid-day columns.

## Deployment and verification

Restart Odoo and upgrade bambus_hr_attendance_ot_fine, bambus_hr_daily_ops,
attendance_custom_report and hr_payslip_excel_report. Review template rates and
salary structures, then recompute draft payslips after approving attendance.
Existing finalized salary lines are not rewritten by the upgrade.

Automated checks cover real salary lines for 100 + 150 = 250, both wage types,
public holidays, Hourly exclusion, unworked weekly offs, paid leave, ignored
items after refresh/recompute, stale reviews, invalid hours and HR/company access.
The Chromium suite renders the production OWL editor, deletes an individual fine,
approves remaining items and verifies that employee rows stay mounted.

For the installed popup check, run:

```
python bambus_hr_daily_ops/tests/browser/verify_combined_review.py \
  --url http://localhost:8071 --db raaviya_weekly_off_test
```

This check requires an isolated database with `test` in its name and removes its
employee, contract, attendance and review fixtures when finished.

### Monthly paid-off switches and contract wages

The effective employee template wins, followed by the company template.
Inactive or out-of-date templates fall back as usual. Without an effective
template the existing weekly-off credit remains and the new public-holiday
credit is disabled. Contract start/end dates and public-holiday precedence
still apply. Recompute draft payslips after changing a policy; completed salary
lines and approved attendance snapshots are not rewritten automatically.

The daily attendance employee row and combined review show the contract's
**Daily Wage**, **Hourly Rate**, or **Monthly Wage** for that date. These are the
configured contract values, separate from the derived rates used to calculate
adjustments. The native review form shows the same wage information.

Upgrade `custom_hr_payroll`, `bambus_hr_attendance_ot_fine`,
`bambus_hr_daily_ops`, `attendance_custom_report`, and `hr_payslip_excel_report`
(where installed). The dashboard review overlay mounts on the document body;
its content scrolls within bounded rows while the header and approval buttons
stay visible. Installed-browser verification covers desktop, narrow mobile, and
short landscape viewports using actual wheel input and the full asset bundle.

### Client verification example

Use a September Monthly wage of 9,000 (30 calendar days, 300/day), a calendar
of 8 hours/day, and a full-day
template threshold of 9 hours for the threshold regression check. Enable both
paid-off switches. For one weekly off and one public holiday, test separately:

| Attendance | Worked days | Normal day credit | Extra earning |
| --- | --- | --- | --- |
| No punches | 0 | 1 day / 300 | 0 before an HR approval |
| 4 hours | 0.5 | 1 day / 300 | Approved amount under the day policy |
| 9 hours | 1 | 1 day / 300 | Approved amount under the day policy |

Change the punches from 8 hours (0.5 day) to 9 hours (1 day) and back.
The displayed worked-day fraction must follow the change. Compute Sheet must
refresh Worked Days & Inputs and salary totals. With 1.5x Salary and a 300/8
hourly salary, 4 approved hours add 225 to the normal 300, totaling 525 before
other earnings/deductions. Check the payroll review and attendance Monthly
Summary exports against the payslip. Disable each paid-off switch to verify
no-punch credits disappear while approved extra earnings stay separate.

### Calendar-month rates (20 October 2026)

Normal pay and monthly salary-derived OT/fine review rates use the calendar days
in each attendance date's month. Daily rate is not rounded before regular-pay
aggregation; final adjustment amounts retain currency rounding. February leap
years are included. The payslip period and employment range never replace the
full calendar-month divisor. For periods crossing months, each date uses its own
month. Existing Daily/Hourly contract and fixed-amount rules remain unchanged.

Approved attendance amounts remain authoritative snapshots. Compute Sheet
refreshes draft normal pay with the new divisor but keeps approved OT/fine
amounts; reapproval is an explicit HR action. Finalized salary lines are not
automatically rewritten by the upgrade. Reports retain the same precedence.
