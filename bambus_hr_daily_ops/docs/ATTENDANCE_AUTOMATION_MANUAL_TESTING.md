# Attendance Automation — Manual Testing

Use a test database and test employees. Enable developer mode first. Use a
09:00–17:00 schedule, monthly salary ₹12,000, and an eight-hour/480-minute day
unless a scenario says otherwise.

## How to record a result

For each scenario: save the template, create the punches, open Attendance for
the date, record the dashboard hours, open the OT/Fine dialog, and compare the
actual result with the expected result. Mark **Pass** only when all values match.

| ID | Configuration | Punches | Expected result |
| --- | --- | --- | --- |
| L01 | Late on; grace 5 | 09:04–17:00 | 0 fine minutes |
| L02 | Late on; grace 5 | 09:05–17:00 | 0 fine minutes |
| L03 | Late on; grace 5 | 09:12–17:00 | 7 fine minutes |
| L04 | Late off | 09:30–17:00 | 0 late fine |
| E01 | Early exit on; grace 5 | 09:00–16:57 | 0 early fine |
| E02 | Early exit on; grace 5 | 09:00–16:45 | 10 fine minutes |
| B01 | Break on; allowance 45 | Break 40 minutes | 0 break fine |
| B02 | Break on; allowance 45 | Break 45 minutes | 0 break fine |
| B03 | Break on; allowance 45 | Break 60 minutes | 15 fine minutes |
| O01 | OT on; minimum 60 | 09:00–17:59 | 0 OT |
| O02 | OT on; minimum 60 | 09:00–18:00 | 60 minutes OT |
| O03 | OT off | 09:00–19:00 | 0 OT |
| O04 | Start offset 15 | 09:00–18:00 | 45 minutes OT |
| O05 | Fixed start 17:30 | 09:00–18:00 | 30 minutes OT |
| O06 | Max duration 60 | 09:00–20:00 | 60 minutes OT |
| O07 | Fixed end 18:00 | 09:00–19:00 | OT stops at 18:00 |
| R01 | Exact rounding | Eligible 44 minutes | 44 minutes |
| R02 | 15-minute rounding | Eligible 44 minutes | 30 minutes |
| R03 | 30-minute rounding | Eligible 44 minutes | 30 minutes |
| R04 | 60-minute rounding | Eligible 44 minutes | 0 minutes |
| W01 | Weekly off: Not Payable | Work 09:00–15:00 | 0 OT |
| W02 | Weekly off: All Worked Hours | Work 09:00–15:00 | 6 hours OT |
| H01 | Holiday: Not Payable | Work 09:00–15:00 | 0 OT |
| H02 | Holiday: All Worked Hours | Work 09:00–15:00 | 6 hours OT |
| T01 | Employee template present | Different company default | Employee template wins |
| T02 | Employee template expired | Valid company default | Company template wins |
| T03 | Both templates unavailable | Contract/company legacy rules | Legacy fallback is used |
| S01 | Salary exactly slab maximum | ₹9,000 | Lower slab rate |
| S02 | Salary in middle slab | ₹10,000 | Middle slab rate |
| S03 | Salary above last limit | ₹13,000 | Open-ended slab rate |

## Amount checks (2 final hours, ₹12,000 monthly salary)

| Method | Rate | Expected amount |
| --- | ---: | ---: |
| Fixed Amount | ₹80 | ₹80 |
| Fixed Amount per Hour | ₹80 | ₹160 |
| Half Day | — | ₹200 |
| Full Day | — | ₹400 |
| Regularize | — | ₹0 |
| 1x Salary | — | ₹100 |
| 1.5x Salary | — | ₹150 |
| 2x Salary | — | ₹200 |
| Fine per salary minute | — | ₹100 |

## Screenshot checklist

Capture these after a scenario passes and save them in `docs/images/`:

1. `02-debug-mode.png` — Settings showing developer mode enabled.
2. `03-template-header.png` — name, company, active and dates.
3. `04-late-early.png` — late/early configuration.
4. `05-breaks.png` — break configuration.
5. `06-overtime.png` — OT window, minimum, rounding and policies.
6. `07-slabs.png` — full salary slab table.
7. `08-assigned-employees.png` — assigned employee list.
8. `09-attendance-input.png` — punches used for the scenario.
9. `10-dashboard-ot.png` — Overtime card filter and matching employees.
10. `11-ot-dialog.png` — detected hours, final hours, rate and amount.
11. `12-dashboard-fine.png` — Fine card filter and matching employees.
12. `13-fine-dialog.png` — detected hours, final hours and deduction.
13. `14-saved-snapshot.png` — saved calculation information.
14. `15-payroll.png` — payslip result using the saved value.

Do not include real employee personal or salary information in documentation.
