# Odoo 18 runtime warning cleanup

The later supplied local log includes extra Employee Info/Loan/Salary Advance
messages and Apps Markdown-description rendering warnings. See the
[additional cleanup and newer upgrade versions](ADDITIONAL_RUNTIME_WARNINGS.md).
That follow-up explicitly excludes `bambus_saas_client`.

This change addresses messages reproduced in the shared payroll test/upgrade
and normal HTTP logs. It does not disable Python/Odoo warning logging or change
the log level. Logs from a separate customer/local installation still need to be
checked after deploying the same source and upgrading the affected modules.

## Corrections

| Message | Source correction |
| --- | --- |
| `_company_default_get` is deprecated | Payroll company defaults use `env.company`, preserving the selected company |
| `decimal_precision.get_precision` is deprecated | Payroll floats use the same named precision through `digits='Payroll'` / `digits='Payroll Rate'` |
| `ustr()` deprecation | Payslip names use Babel's existing Unicode result directly |
| Constraint references missing `sunday_wage_rate` / `saturday_wage_rate` | Remove the dead constraint for fields absent from this module; do not impose a new limit on current template rates |
| Duplicate field labels | Distinguish calendar days, worked days/hours, late-login hours, pay types, source/display descriptions and leave status; keep technical fields and values |
| Missing license / report description | Explicit LGPL-3 manifest metadata (same as the previous default), and an XLSX report model description |
| Icon titles / alert roles | Add descriptive icon titles and appropriate status/alert roles in payroll/attendance views |
| `kanban-box` is deprecated | Use Odoo 18 `card` templates for payroll rules, structures, payslips and batches |
| Fine split mismatch | Remove the invalid comparison of approved/post-grace fine hours with raw late/early/gap minutes; preserve both measures and all amounts |
| Importing test framework outside test mode | Remove eager test imports from the two report packages; Odoo discovers their test packages in test mode |

Payroll salary formulas, template policies, precision names, raw punches, saved
HR approvals and salary-line amounts are not changed by this cleanup. Normal
payroll upgrades still require the existing coordinated modules and normal
deployment validation. In particular, seconds tolerance and the manual dashboard
punch synchronization gap are separate from warning cleanup.

## Upgrade

Pull the updated source, restart Odoo and upgrade these modules on the intended
database before rechecking its logs:

| Module | Version |
| --- | --- |
| hr_payroll_community | 18.0.1.1.0 |
| custom_hr_payroll | 18.0.4.17.0 |
| bambus_hr_attendance_ot_fine | 18.0.3.33.0 |
| bambus_hr_daily_ops | 18.0.1.88.0 |
| attendance_custom_report | 18.0.1.11.0 |
| hr_payslip_excel_report | 18.0.4.16.0 |
| hr_attendance_location | 18.0.1.0.1 |

Using the existing Odoo executable/configuration, the upgrade module list is:

```text
-u hr_payroll_community,custom_hr_payroll,bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report,hr_payslip_excel_report,hr_attendance_location --stop-after-init
```

Run the upgrade with the regular HTTP/cron process stopped, then restart the
regular service and reload the browser. Do not replace the customer's executable,
configuration path or database name with the shared test environment's values.
Only upgrade modules already installed for the deployment; this is not a request
to install optional payroll accounting, loan or location modules.

## Verification

The installed browser check for the four payroll card types and exact decimal
salary computation is:

```sh
python custom_hr_payroll/tests/browser/verify_payroll_runtime_views.py \
  --url http://localhost:8071 --db YOUR_TEST_DATABASE
```

It creates and removes its own fixtures. Use an isolated database containing
`test` in its name, with Playwright/Chromium installed. The existing payroll report
browser check covers the wizard and both Excel download formats.

Final local evidence on `raaviya_attendance_test`: **237 tests passed**, with
**zero WARNING and zero ERROR log entries** during the coordinated upgrade/test
run. Fresh normal HTTP startup and both installed browser checks also produced
zero WARNING/ERROR entries. The four updated cards opened their forms, exact
1,234.56 salary precision was retained, and both payroll Excel downloads passed.
The report tests were still discovered after removing eager test imports.

These results cover this source/environment. They do not establish that a
separate local terminal has no additional messages or that production is deployed.
