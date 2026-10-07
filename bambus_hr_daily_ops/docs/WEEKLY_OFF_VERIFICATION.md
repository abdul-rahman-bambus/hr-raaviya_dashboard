# Verify template-driven weekly off

Use a test database and a test employee. These checks create attendance and payroll
records; keep them separate from live payroll. Automated tests create isolated
fixtures and roll them back.

## Reproduce the Sunday configuration shown in the UI

1. Duplicate the monthly automation template for testing. Keep it active and use
   an effective period containing **4 October 2026 (Sunday)**. The screenshot's
   23 September 2026–23 September 2027 period includes that date.
2. In Weekly Off, select **Selected Weekdays**, check **Sunday only**, and choose
   **All Worked Hours**.
3. In Overtime, enable **Overtime Rule**, set Minimum Overtime to **0**, choose
   **Fixed Template Rate = 100**, and **Fixed Amount per Hour**. This makes the
   expected amount easy to verify, independently of salary rates.
4. Assign the template directly to the test employee, or select it as the company
   default and leave the employee's individual template empty. Ensure a monthly
   contract is valid for the date. Use the employee/calendar timezone for punches.
5. Enter Sunday attendance **09:00–12:00** and **13:00–16:00**. Refresh/recompute
   the daily attendance using the normal attendance dashboard workflow.
6. Expect **6 worked hours**, **6 detected overtime hours**, and no scheduled-day
   late/shortfall fine. Weekly off includes all worked sessions; the midday gap
   is not worked time.
7. Open **OT** from the employee's daily dashboard row. Confirm detected hours
   are 6; change final payable hours to **5** and save. Expect state **Updated**,
   rate **100**, and the saved amount **500**.
8. Calculate a draft payslip covering the date. Expect weekly-off worked hours
   **6**, payable OT hours **5**, and OT amount **500**. The OT earning requires
   an OT salary rule using the saved attendance amount. Overall net salary also
   depends on the other salary rules, allowances, and deductions.
9. Download Attendance Report → Monthly Summary for that employee/date. The day
   should be classified as Weekend, with OT **05:00** and amount **500**. Raw
   attendance remains 6 hours. A half/full-day fraction depends on the configured
   thresholds, so do not assume 6 hours equals a full worked day.
10. Repeat payslip calculation and export. OT must remain 5 hours/500 and must not
    produce duplicate earnings or multiply the saved amount by the number of punches.

## Negative and boundary checks

| Change | Expected result |
| --- | --- |
| Not Payable, on a new unreviewed test record | No proposed weekly-off OT; actual worked hours remain available. |
| Disable Overtime Rule | No proposed weekly-off OT even with All Worked Hours. |
| Minimum OT 60 minutes; work 59/60/61 minutes | Proposed OT 0 / 1 hour / 61 minutes. |
| Sunday unchecked in Selected Weekdays | Sunday is not classified as weekly off, even if the schedule has no Sunday shift. |
| Assigned Working Schedule | Dates without valid work periods are weekly off; selected checkboxes are ignored. |
| Employee template differs from company default | The effective employee template takes priority. |
| Employee template inactive, future, or expired | Effective company template applies; otherwise use the assigned schedule. |
| Sunday is also a public holiday | Public-holiday policy and bucket take priority; the day is counted once. |
| Exclude the daily OT review | Payroll and report OT hours/amount become zero. |
| Save Regularize in OT review | Saved payable amount is zero. |
| Change a template rate after HR saved the result | Existing saved rate/amount remain the HR snapshot. New proposals use the new rate. |

Changing a template does not erase a saved HR correction. Test policy suppression
with a new/unreviewed date, or explicitly exclude the existing review when needed.

## Automated execution

Run against a disposable database with the four modules installed. The report
suite's selected-template integration tests require the automation modules too.

```bash
./odoo-bin -c <config> -d <test_database> --http-port=8070 \
  -u custom_hr_payroll,bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report \
  --test-enable \
  --test-tags /bambus_hr_daily_ops,/custom_hr_payroll,/attendance_custom_report \
  --stop-after-init --log-level=test --workers=0
```

Require exit code 0 and the current-run summary with a nonzero test count,
zero failures, and zero errors. Do not infer success from a running server alone.

Coverage includes all seven weekdays, template precedence/effective dates,
historical contracts, alternating/date-limited schedules, public-holiday overlap,
split punches, local Sunday with a Saturday UTC check-in, strict policy suppression,
minimum-minute boundaries, HR-saved/excluded amounts, salary-rule execution,
repeated payslip computation, snapshot retention, and generated XLSX values.

These tests validate Odoo model/action behavior and workbook output. They do not
validate your production employee data, every installed third-party salary rule,
or browser rendering/click behavior in your deployed instance.
