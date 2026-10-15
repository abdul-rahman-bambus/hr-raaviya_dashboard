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
- A Monthly configured weekly off with no attendance receives one paid day.
  No leave request is created and no leave balance is consumed. Daily and Hourly
  contracts receive no unworked weekly-off credit. Holiday classification wins
  when a date is both a holiday and weekly off. Credits respect contract dates.
- Daily day pay uses daily_wage; Monthly day pay uses wage / 30, consistent with
  the existing adjustment calculations. Special-day normal pay uses actual
  worked hours / the calendar's hours per day. Normal days keep attendance day
  fractions and paid leave. Regular pay, paid-weekly-off amount (included in
  regular pay), and paid-weekly-off days are visible in Payslip → Payables.

The standard BASIC salary rule uses the new regular-pay total for template-driven
Daily/Monthly payroll and existing billable hours for Hourly payroll. Legacy
Monthly payroll without an effective template retains contract wage. OT and PH
remain separate salary-rule inputs, each paid once. Verify that the employee's
salary structure includes the corresponding OT / PH rules; independent custom
BASIC rules must use total_regular_pay_amount to apply these same rules.

Reports recognize the PAID_WEEKLY_OFF worked-day bucket. The summary's
Paid Weekly-off Days column represents Monthly weekly offs without attendance;
public holiday and weekly-off work remain separate classifications.

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
