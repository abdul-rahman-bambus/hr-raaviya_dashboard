# Withheld worked special dates: Payable Days correction

Withholding normal credit on a worked Monthly weekly off or public holiday
already removed that date's normal salary. Its WEEKEND/HOLIDAYS generated row
could still add the worked fraction to Payable Days, so the paid-day count
disagreed with the decision. The correction excludes that withheld fraction
from generated paid days and also prevents the default calendar-row fallback
when the special-work OT policy is disabled.

Actual punches, work hours and special-day work classifications remain. Approved
OT/holiday earnings and fines retain their saved amounts. Restoring normal credit
reapplies the existing eligibility rules and adds the appropriate day credit
without duplication. A public holiday overlapping a weekly off uses holiday
precedence. The withheld counters apply only to Monthly normal credit.

## Supplied October example

The test contains six regular attended dates, four Sundays and two paid holidays.
Both 18 and 25 October were worked. HR withheld normal Sunday credit for 18 October
and separately approved its work earning. On 25 October the first punch starts
at 09:45:34, so existing strict thresholds classify that date as half a worked day.

| Result | Correct value |
| --- | ---: |
| Regular attendance-day credit | 6 |
| Eligible normal weekly-off credit | 3 |
| Paid public holiday credit | 2 |
| Payable Days | **11** |
| Basic salary | **2,838.71** |
| Saved approved Sunday earnings | **773.75** |
| Saved approved fines | **294.55** |
| Net pay | **3,317.91** |

Generated rows are DAYSWORKED 6, PAID_WEEKLY_OFF 2.5, PAID_PUBLIC_HOLIDAY 2,
and WEEKEND 0.5: **11 paid days**. WEEKEND retains both Sundays' actual work hours.
The attendance statistics still show 1.5 weekly-off worked-day equivalents and
the report's Present Days still includes those equivalents. These work metrics
are distinct from normal paid-day credit; separately paid OT does not restore a
withheld normal day.

## Upgrade and manual check

1. Upgrade **bambus_hr_attendance_ot_fine 18.0.3.32.0** and restart Odoo. Keep the
   previously coordinated payroll/reporting modules installed and current.
2. Open the existing **draft/verification** payslip and run **Compute Sheet**.
   Do not recreate the punches, decisions or approvals.
3. Check Worked Days: the generated paid-day total is 11 in the example above.
4. Confirm Basic/OT/Fine/Net match the values above. The correction must not
   reprice saved approvals or change actual punches/hours.
5. Export both **Payslip Summary** and **Payroll Review**, including Draft. Check
   Payable Days 11 and the same salary amounts in both workbooks.
6. On an isolated test, restore the 18 October credit and recompute: Payable Days
   becomes 12, Basic increases by 8,000 / 31 and approved earnings/fines remain.
7. Repeat withholding/restoration on a worked public holiday. With no normal paid
   credit, its generated HOLIDAYS row can contain actual hours and zero paid days.

Finalized payslip salary and worked-day rows remain saved snapshots. Exporting
does not refresh them or change payroll state. This correction does not add
seconds tolerance: use exact 09:45:00 in a separate clean full-day test if desired,
then review affected approvals explicitly and recompute its draft.

## Validation

On the isolated `raaviya_attendance_test` database, **228 Odoo tests passed** with
zero failures/errors. Coverage includes worked weekly-off and public-holiday
withholding/restoration, the disabled-OT fallback, both payroll report paths,
the supplied 11-day/3,317.91-net reproduction, and finalized row/amount retention.
Installed Chromium also passed the dashboard decision/audit workflow and both
real XLSX downloads: a withheld worked Sunday retained eight actual hours,
approved OT 250 and fine 10 (Net 240), with zero normal payable days.

```sh
python bambus_hr_daily_ops/tests/browser/verify_paid_day_withholding.py \
  --url http://localhost:8071 --db YOUR_TEST_DATABASE
```

Requires Playwright, Chromium and openpyxl. Use an isolated database whose name
contains `test`; browser fixtures are created and removed. These results do not
establish production deployment or client acceptance.
