# Attendance without History dependency

## Sources of truth

Daily Attendance uses `bambus.attendance.dashboard`, a stateless service. It reads
current `hr.attendance` punches, effective calendars/templates and Time Off. It
creates no History records and no review record merely to display a date.

`bambus.attendance.day.review` stores explicit employee/date/company decisions:
manual status, approved OT/fines, exclusions, exception coverage and Hourly Pay
corrections. It has no parent sheet. Its punch times, worked hours, current leave
and contract are non-stored computations. Opening a review refreshes proposals;
it never reprices a saved approval. An unchanged refresh does not invalidate an
already-open review. Real punch/schedule changes still invalidate stale approval
forms. Revoking a status clears only that status; it never deletes money decisions.

The active company owns the dashboard roster, even when several companies are
checked. A write for an employee in another active company is rejected. Existing
review and payroll access checks remain enforced.

Dashboard time edits now create/update actual punches and therefore invoke the
normal attendance detection hooks. On split-punch dates, editing the first/last
boundary preserves intermediate sessions and lunch gaps. Use the pencil list for
removing punches. An open punch is not completed payable work. Status/time edits
do not silently approve numeric fines/OT or overwrite saved approvals.

Thresholds, fine-only pay, reviewed-exception intervals, wage pricing, paid special
day eligibility/withholding and Time Off rules are unchanged. Payroll and both
report formats now read independent review decisions. Exports still read saved
salary lines; recompute drafts explicitly. Finalized salary amounts are preserved.

The History models, actions, menus, dashboard History buttons and daily-sheet
creation cron are removed. Saved decisions can be inspected through a read-only
form, while employee Logs retains the existing time/adjustment audit trail.

## Upgrade and preservation

Deploy these coordinated versions in one maintenance upgrade:

| Module | Version |
| --- | --- |
| bambus_hr_daily_ops | 18.0.1.92.0 |
| bambus_hr_attendance_ot_fine | 18.0.3.34.0 |
| attendance_custom_report | 18.0.1.12.0 |
| hr_payslip_excel_report | 18.0.4.19.0 |

Stop application workers and take a database/filestore backup first. Validate the
upgrade on a separate database containing `test` before production. For example:

```sh
python odoo-bin -c <config> -d <test_database> \
  -u bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report,hr_payslip_excel_report \
  --stop-after-init
```

The pre-migration renames the old line table and model metadata in place. Record
IDs remain unchanged, preserving existing foreign keys such as payslip detail
links. Saved methods, amounts, users/timestamps, exclusions, JSON interval
coverage, Hourly Pay corrections and manual statuses remain. The parent sheet FK
is removed; an integer `legacy_sheet_id` is retained solely as an archive reference.

Raw pre-upgrade lines are copied to `bambus_legacy_attendance_review_archive`.
The original parent sheet table is retained as database audit evidence, without
an active model or calculation dependency. These archives are not read by any
runtime dashboard, payroll or report. Do not delete them as part of this upgrade.
No payslip is recomputed, confirmed, deleted or backfilled by the migration.

The upgrade fails transactionally rather than guessing if it finds duplicate
employee/date/company decisions, incomplete keys, employee/company mismatches,
or audited manual times without actual Punch Logs. Review those entries and
enter verified actual punches before retrying. Never manufacture punches simply
to pass the guard. A backup is required for rolling back the application/database
schema; archives alone are not a complete rollback procedure.

## Validation scope

See [test evidence](../TESTING_CHECKLIST.md) and [release readiness](GO_LIVE_READINESS.md)
for the final 254-test backend run, 17 OWL tests, installed browser checks,
fresh-install acceptance tests and migration/rollback checks. Tests
exercise the flow with neither legacy History model registered, all wage types,
manual time edits and punch deletion, preserved saved money, company switching,
review conflict checks, payroll and both exports. Existing coverage also exercises
threshold boundaries, leave, special days, withholding, calendar-month rates,
Hourly caps, saved report reconciliation and bulk confirmation.

Seconds/tolerance policy is intentionally unchanged. Automated success does not
establish production deployment or replace checking the customer's configuration.
