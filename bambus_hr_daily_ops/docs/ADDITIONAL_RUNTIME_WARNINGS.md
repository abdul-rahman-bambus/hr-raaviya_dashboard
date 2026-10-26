# Additional warnings from the local 26 October log

This follows the first Odoo 18 cleanup. The supplied local log includes Employee
Info, Loan Management and Salary Advance modules that were not in the earlier
67-module payroll test registry. Validation now uses a separate isolated test
database with those modules and their dependencies installed.

## Fixed sources

- Employee family: remove the unsupported model-field `invisible` parameter;
  visibility belongs to views. Remove `tracking` from the family birth date,
  because the family model has no mail-thread tracking implementation. No family
  values, links or views are deleted.
- Employee documents: give identification/passport expiry dates and attachments
  distinct labels. Technical field/relation names and stored attachments remain.
- Salary Advance: replace obsolete `track_visibility` with supported mail-thread
  `tracking=True` for status changes. Support single/list creates with an
  individual sequence for each request.
- Loan Management: support the multi-create API while preserving sequential
  pending-approved-loan checks and unique sequence names. Normal installments,
  amounts and approval logic are unchanged.
- Apps descriptions: add plain descriptions to the three custom module manifests.
  Odoo's Apps renderer treats fallback README text as reStructuredText; Markdown
  fenced shell examples caused the pasted docutils warnings/errors. Full Markdown
  developer guides remain available in the repository.

**bambus_saas_client is excluded.** No source, manifest, installation state,
configuration, database records or log filters for that module are changed. Its
not-installable/missing-module messages may remain in the local installation.
Warnings are corrected at their sources, not hidden with logging filters or
permissive field-parameter overrides.

## Upgrade the affected installed modules

| Module | Version |
| --- | --- |
| hr_employee_updation | 18.0.1.0.1 |
| ohrms_loan | 18.0.1.0.1 |
| ohrms_salary_advance | 18.0.1.0.1 |
| custom_hr_payroll | 18.0.4.18.0 |
| bambus_hr_daily_ops | 18.0.1.89.0 |
| hr_payslip_excel_report | 18.0.4.17.0 |

Pull the source, stop the regular Odoo process, upgrade these modules on the
intended local database with the existing executable/configuration, then restart
and refresh the browser. The module list for the existing upgrade command is:

```text
-u hr_employee_updation,ohrms_loan,ohrms_salary_advance,custom_hr_payroll,bambus_hr_daily_ops,hr_payslip_excel_report --stop-after-init
```

These versions include the previous payroll cleanup. Do not use the shared test
database name for the customer command, install optional modules on production
just for this check, or upgrade/disable the excluded SaaS module. Existing module
description text needs the upgrade; a process restart alone does not replace it.

## Validation

Focused tests exercise dictionary/list creation, sequence uniqueness, pending
loan validation (including a pending record earlier in the same batch), salary
advance state tracking and strict Apps-description rendering. The full payroll,
attendance and report suite is also run with the extra modules installed. Fresh
normal HTTP startup and the affected forms/Apps descriptions must be checked
separately from test mode.

Final local evidence: an expanded **85-module** registry including all affected
Employee Info/Loan/Salary Advance dependencies passed **243 tests**, with zero
WARNING/ERROR entries during the coordinated upgrade/tests. Fresh normal HTTP
startup and sequential browser checks also logged zero warnings/errors. The
employee, loan and advance forms opened; batch sequences and advance status
worked; all three Apps descriptions and both payroll Excel downloads passed.
The earlier smaller registry did not cover these additional module sources or
explicitly force Apps-description rendering.

```sh
python custom_hr_payroll/tests/browser/verify_additional_runtime_warnings.py \
  --url http://localhost:8071 --db YOUR_TEST_DATABASE
```

Requires Playwright/Chromium and the affected modules installed on an isolated
database containing `test` in its name. Run browser checks sequentially when
examining clean logs, to avoid concurrent development-asset rebuild retries.
The customer registry contains additional modules; these results establish the
listed source fixes, not direct access to the customer's terminal or deployment.
