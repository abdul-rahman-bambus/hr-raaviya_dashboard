# Manual payroll acceptance: three wage types

Run in a restored, neutralized test database. Keep the original database and
backup intact. Do not clear all transactions to reproduce an existing failure.
Existing long/open punches must be reviewed rather than automatically shortened.

## Setup

Create three clearly named test employees. Contract dates: 20–26 October 2026.
Monthly wage 31,000; Daily wage 1,000; Hourly rate 100. Use Asia/Kolkata and
a Monday–Saturday calendar with 09:00–13:00 and 14:00–18:00 (eight hours/day).
Set the Odoo test user timezone to Asia/Kolkata before creating the holiday;
verify that its displayed local range covers only 26 October. Odoo adjusts
public-holiday creation when the user/calendar timezones differ.
October Monthly daily rate is 31,000 / 31 = 1,000. Assign the intended salary
structure; confirm the BASIC category has the appropriate base rule, plus
GROSS/NET and approved OT/PH/fine rules. Avoid duplicate BASIC rules for one wage.

Monthly and Daily can share one template: Sunday weekly off; both paid-off
checkboxes enabled; full-day basis assigned schedule; half day four hours;
late grace five minutes; per-minute daily-salary fine; early exit disabled;
allowed break 60 minutes. OT starts 15 minutes after the shift, rounding 60
minutes, fixed 100/hour. Weekly-off work: all hours. Holiday work: all hours
as overtime, 1x salary. Add 26 October as a test-calendar public holiday.

Hourly uses a separate template: no OT/fine rules, template hourly-cap override
enabled, cap zero (unlimited). The paid-unworked switches remain Monthly-only,
even when Monthly and Daily share a template.

## Baseline entries

Create actual hr.attendance punches in local time, not dashboard time snapshots.
Do not create leave or manual attendance-status overrides.

| Date | Actual entries | Hours |
| --- | --- | ---: |
| 20 October | 09:00–13:00; 14:00–18:00 | 8 |
| 21 October | 09:00–13:00 | 4 |
| 22 October | None | 0 |
| 23 October | 09:00–13:00; 14:00–18:00 | 8 |
| 24 October | 09:00–13:00; 14:00–18:00 | 8 |
| 25 October | None; Sunday | 0 |
| 26 October | None; public holiday | 0 |

Generate one standard batch for 20–26 October and keep its three computed slips
Draft. Include Draft when exporting Payslip Summary. No adjustments approved.

| Expected | Monthly | Daily | Hourly |
| --- | ---: | ---: | ---: |
| Actual hours | 28 | 28 | 28 |
| Regular worked equivalents | 3.5 | 3.5 | n/a |
| Completed attended dates | 4 | 4 | 4 |
| Paid unworked Sunday | 1,000 | 0 | 0 |
| Paid unworked holiday | 1,000 | 0 | 0 |
| Basic / Net | 5,500 | 3,500 | 2,800 |

Compare Salary Computation, Basic/Gross/Net header fields, and the exported row.
Do not add Other Allowances to OT/PH twice; it now excludes those components.

## Independent corrections and adjustments

Return to baseline before each independent test. Recompute the existing draft.

| Test | Change and expected result |
| --- | --- |
| Correct a half day | Add 14:00–18:00 on 21 October: Monthly 6,000; Daily 4,000; Hourly 3,200. Remove it and recompute: restore baseline. |
| Disable paid public holiday | Monthly 4,500; Daily/Hourly unchanged. Restore the switch. |
| Disable paid weekly off | Monthly 4,500; Daily/Hourly unchanged. Restore the switch. |
| Missing checkout | An open Hourly punch on 22 October adds no billable hours/completed attendance date. Closing it for two actual hours adds 200 and one date after Compute Sheet. |
| Multiple sessions | Split a day's punches into more nonoverlapping sessions with the same total hours: hourly earnings/day count unchanged. |
| Daily cap | Set Hourly daily cap to six: baseline billable hours 6+4+6+6=22, pay 2,200; raw hours stay 28. Restore zero cap. |
| Late fine | On 23 October use 09:10–13:00; 14:00–18:10. Eight actual hours retain normal day pay. Expect five chargeable late minutes, approximately 10.42 at 1,000 / 480 per minute. Pending fine does not reduce Net; approval reduces it once. |
| Ignore/Cancel | Ignore then Cancel must not save an exclusion. Ignore then Approve Remaining Items saves it and prevents the fine from returning on recalculation. |
| Regular OT | Extend 24 October checkout to 19:15. With configured 18:15 OT start, approve final one hour at 100. Monthly/Daily Net increases by 100; before approval no extra earning. Hourly instead pays all actual hours at its rate, subject to its own cap. |
| Worked Sunday and holiday | Add eight hours on each of 25 and 26 October. Monthly normal pay stays 5,500; Daily normal pay becomes 5,500; Hourly becomes 4,400. Approve eight Sunday hours at 100 (800) and eight holiday hours at 1x daily salary (1,000). Monthly/Daily total becomes 7,300; Hourly stays 4,400 with its separate no-OT template. Verify only approved extra amounts are paid. |
| Export without recompute | Edit attendance, export, and verify saved salary does not change. Compute Sheet then export must show the updated salary. |
| Finalized salary | In a disposable copy, mark a test slip finalized and change punches. Compute Sheet must not rewrite saved finalized lines. |

Record expected/actual Basic, OT, PH, deductions and Net for each case. Check both
Excel reports against saved salary. PDF and production deployment are separate.

## Known remaining acceptance gaps

Dashboard manual time entry still saves a daily snapshot/audit without syncing
actual punches or invoking detection. These tests deliberately use actual punches.
Manual Present overrides can raise report Present Days without changing actual
worked hours; review rather than silently clearing them. Full restored-server UI
parity also needs all installed theme/SaaS add-on sources available locally.

## Reviewed attendance exceptions (22 October 2026)

Monthly/Daily templates now offer **Day Pay for Reviewed Attendance Exceptions**.
The default keeps actual-hours classification. Opting into **Regularize Reviewed
Exception Time** lets saved session-specific HR decisions cover missing scheduled
time for day pay, while approved fines remain separate and punches stay intact.
Hourly rules retain their own payable-hour review. Half Day Leave now suggests
the missing half and asks HR to confirm the half and paid/unpaid Time Off type.
The last approval clears the review filter; rate displays include correct units.
No threshold tolerance change is included.

See [configuration, manual cases and upgrade versions](REVIEWED_EXCEPTION_DAY_PAY.md).
