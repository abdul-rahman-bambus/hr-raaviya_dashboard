# Correcting attendance after approval

Upgrade **bambus_hr_daily_ops to 18.0.1.97.0**, restart Odoo and reload the client.
Existing approvals and finalized salary lines are not rewritten by the upgrade.

When an actual punch is created, edited, moved or deleted, detection recomputes.
If the calculated Fine or OT proposal changes for an approved or excluded decision,
that decision is superseded and becomes **Needs Review**. The previous hours,
amount, calculation, rate, note, reviewer, review time and fine session coverage
are retained in an audit snapshot. Current decision amounts become zero until
HR reviews the replacement proposal. An unaffected decision remains approved.
No-op writes, metadata-only writes and opening/refreshing the dashboard do not
supersede approvals. Policy-only changes retain the existing saved-decision rules.
Hourly-pay corrections and explicit attendance statuses retain their own workflow.

The Logs popup records punch creation/edit/deletion, before/after times, actor,
log time and any provided correction reason. Bulk punch snapshots retain all
changed records and are limited to the employee concerned. The supersession log
shows the previous approved/excluded amount and current calculated amount.
Reapproval/exclusion appends the replacement result and note. Audit rows cannot
be edited or deleted through the model; archive employees to retain their history.

## HR workflow

1. Correct and save actual Attendance entries, or update punches in Daily Attendance.
2. Refresh Daily Attendance after edits made on another screen/tab.
3. Open **Late / Fine** or **Overtime**, including its **To Review** filter.
   Corrections producing zero hours remain visible for explicit review.
4. Review the warning and corrected proposal. Enter a note if appropriate, then
   **Approve Remaining Items**; Delete/Ignore is saved only on approval. Cancel
   keeps the correction pending. A popup opened before the punch edit cannot save.
5. Use **Compute Sheet** on the existing draft, then export again. Computation and
   confirmation are blocked while a superseded decision in that period still
   requires review. Exports continue to read saved salary lines and report pending
   review flags; they do not recalculate or approve payroll.

Finalized payslip states and salary-line IDs/amounts remain saved. Correcting a
punch does not revise a finalized payroll; use an explicit payroll correction
process. Superseded fine session coverage stops contributing reviewed day-pay
credit while the replacement decision is pending.

Example: an approved fixed fine of 100 becomes a zero proposal after correcting
arrival. Its audit retains 100 and the original approver. HR explicitly approves
zero, recomputes the draft, and the saved fine deduction becomes zero once.

## Automated checks

On an isolated database, run the module/report tests and production OWL tests
as documented in the Daily Ops README. The installed workflow check is:

```sh
python bambus_hr_daily_ops/tests/browser/verify_punch_correction_review.py \
  --url http://localhost:8080 --db YOUR_test_DATABASE
```

It verifies a real fixed-fine approval, native punch correction, preserved OT,
old decision in Logs, zero-value warning/reapproval, blocked draft computation,
and reconciliation of recomputed salary with the downloaded summary workbook.
