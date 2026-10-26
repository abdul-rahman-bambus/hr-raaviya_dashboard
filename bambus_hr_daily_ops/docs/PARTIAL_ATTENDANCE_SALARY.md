# Configure partial attendance salary

Attendance Day Classification is under **Late & Early Exit**, directly below
**Day Pay** (Daily Ops **18.0.1.90.0**). Configure **Half Day Hours**, **Full Day
Basis**, and, for a fixed basis, **Full Day Hours** there. This form layout change
preserves saved values and attendance/payroll calculations. Upgrade the module
and reload the client to display the new location.


## Customer setup

Open **HRMS > Configuration > Automation Rules**, select the employee's effective
Daily or Monthly template, then open **Late & Early Exit**.

Set **Partial Attendance Salary Treatment** to **Normal Day Pay Minus Approved
Fines**. Keep the actual work schedule and configure the fine rules:

- Enable **Early Exit Rule**, grace **0**, to review remaining working time.
- Enable **Late Entry Rule**, grace **5 minutes**, if that is the customer policy.
- Set **Post-Break Late Grace** to **0** if every late-return minute is chargeable.
- Select **Per Minute from Daily Salary** for wage-derived minute deductions.
- Configure **Break Rule** and its allowed minutes for chargeable internal gaps.

Lunch outside the assigned working periods is not fine time. An entirely missing
morning or afternoon on an attended date is included in late/early/gap review,
using the enabled rules. The setting does not create leave requests or silently
approve fines. Actual check-in/check-out and worked hours remain unchanged.

The default option, **Use Half/Full-Day Thresholds**, retains the existing
classification, including any previously configured reviewed-exception policy.
Existing templates keep that default on upgrade. The earlier reviewed-exception
control is hidden while the new normal-day-minus-fines option is active; its
stored value is retained for switching back.

## How salary follows the selected option

| Case | Normal Day Pay Minus Approved Fines | Use Half/Full-Day Thresholds |
| --- | --- | --- |
| Completed positive work during a regular assigned working date | One normal attendance-day credit, even below the half-day target | Existing half/full-day classification |
| Whole working date absent | No attendance-day pay; no automatic absence fine proposal | Existing absence treatment |
| Fine pending review | Normal attendance-day pay; no pending deduction | Existing day fraction; no pending deduction |
| Fine approved | Deduct the saved HR amount once | Deduct the saved HR amount separately from threshold classification |
| Fine ignored, then approval saved | Normal attendance-day pay; zero ignored deduction | Existing day fraction; zero ignored deduction |
| HR edits fine minutes/method/rate | Only the fine amount changes | Existing classification and selected fine method apply |
| Hourly contract | Existing actual/HR-reviewed payable hours and caps | Same existing Hourly rules |

An open punch alone, zero-hour punch or work entirely outside assigned working
periods does not establish normal attendance-day pay. An attended date is counted
once across multiple completed punches. Open punches do not produce a forecast
of remaining early-exit/gap time; close them and refresh/review actual attendance.

This policy applies to Monthly/Daily **regular working dates** under the effective
employee/company template and contract. Weekly offs, public holidays, their paid
credits and HR withholding keep their existing policies. Explicit validated paid
or unpaid leave remains authoritative if another customer uses it; leave time
is excluded from new fine proposals, and its half/hour/full fraction is not also
credited as attendance. No leave is inferred from punches or missing sessions.

Monthly normal pay uses wage / calendar days in the attendance month. Daily pay
uses the daily wage. The per-minute fine divides that day's salary by that date's
scheduled working minutes. Other selectable fine methods keep their own formulas;
HR-approved saved amounts are not repriced by a mode/contract change.

## Basha's manual case

Use **22 October 2026**, a regular working date with these sessions:

- 09:45–14:00.
- 14:45–18:45.

Daily wage: **885**. Actual punches: **09:45–12:00 only**, with zero seconds.
Actual work is **2:15**. Missing scheduled time is **6:00**; lunch is excluded.
With Early Exit enabled and zero grace, the review proposes **Early Exit Fine:
6 hours** even though there is no afternoon punch.

1. Before approval, compute the existing draft: normal day pay is **885**, fine
   deduction **0**. A pending fine remains for HR review.
2. Approve 6 hours with Per Minute from Daily Salary.
3. Run **Compute Sheet** again on the same draft.
4. Check Salary Computation: **Basic 885**, **Fine 643.64**, **Net 241.36**, assuming
   no other salary rules. Calculation: 885 × 360 / 495 = 643.64 after currency rounding.
5. Worked Days must contain **1 normal attendance day** and **2.25 actual hours**.
   The employee has not worked 8.25 hours; no artificial work hours are added.
6. Export Payroll Review and Payslip Summary with Draft included. Check the same
   saved Basic/Fine/Net, one attended/payable date and unchanged actual work hours.

For a Monthly wage of **8,000** on the same date: normal pay is 8,000 / 31,
rounded salary Basic **258.06**, approved fine **187.68**, Net **70.38**.
For an Hourly wage of **53**: 2.25 × 53 = **119.25**, following Hourly policy.

On separate test dates, verify Ignore retains normal day pay, editing the fine
changes only its deduction, and no punches gives no attendance pay/fine proposal.
Repeat the pending/approve/ignore cases for both Monthly and Daily contracts.

For the supplied five-date Daily example, **if all five dates are attended regular
working dates**, Basic becomes **5 × 885 = 4,425**. Existing approved fines of
643.64 + 9.52 + 17.88 remain **671.04**, producing **3,753.96** Net. A partial day
must not disappear from the base day count and then have its fine deducted too.

Use actual Attendance/Punch Log entries for this test. The separately documented
dashboard-only manual-time synchronization gap has not been changed here.

## Upgrade and recomputation

| Module | Version |
| --- | --- |
| custom_hr_payroll | 18.0.4.15.0 |
| bambus_hr_attendance_ot_fine | 18.0.3.31.0 |
| bambus_hr_daily_ops | 18.0.1.86.0 |
| attendance_custom_report | 18.0.1.10.0 |

Upgrade these modules together and restart/reload Odoo. Keep the installed payroll
XLSX reporting module current (18.0.4.14.0 or later); it reads the same attendance
classification and saved payroll amounts. Select the new option explicitly on the
intended Monthly/Daily templates, confirm employee assignments/effective dates,
and recompute existing draft/verification payslips before exporting.

Existing batches and approvals remain. A saved older fine is not expanded or
combined with a second new proposal after a mode change. HR can explicitly edit
its final hours/calculation if it needs correction. Saved approvals also need HR
review if punches or leave subsequently change; recomputation preserves approved
amounts. Finalized salary/detail rows are not rewritten by Compute Sheet. Exports
read saved salary lines and do not approve/recompute payroll or record payment.

The strict thresholds and deferred threshold tolerance retain their existing
behaviour in threshold mode. No general time-format change is included.

## Local validation

The isolated test database passed **224 Odoo tests** with zero failures/errors,
including 20 partial-salary cases and the backend asset checks. The production
OWL Chromium suite passed **16 tests**. Installed Chromium verified the template
selector, six-hour review proposal and approval navigation, Monthly/Daily/Hourly
payslip amounts, saved deduction rate units, both XLSX downloads and the explicit
half-leave confirmation/Cancel path. This does not establish production deployment.
The installed threshold/reviewed-interval workflow also passed separately,
including legacy fine reassessment, Cancel/audit and both exports.

Run the installed checks sequentially on an isolated database containing `test`
in its name (fixtures are created and removed):

```sh
python bambus_hr_daily_ops/tests/browser/verify_reviewed_day_pay.py \
  --fine-only --url http://localhost:8071 --db YOUR_TEST_DATABASE
python bambus_hr_daily_ops/tests/browser/verify_reviewed_day_pay.py \
  --url http://localhost:8071 --db YOUR_TEST_DATABASE
```
