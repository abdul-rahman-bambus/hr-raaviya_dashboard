# Local Attendance History removal rehearsal

Use the Python/virtualenv that runs Odoo. It must provide `psycopg2`; a current
PostgreSQL `psql` client must be installed or configured through `pg_path`.
The PostgreSQL user in the original config needs `CREATEDB` permission.

## 1. Restore before merging/upgrading

This script works without importing Odoo or loading any add-on. From this
repository, run:

```sh
python3 scripts/odoo_test_restore.py restore \
  --config /path/to/your/odoo.conf \
  --backup /tmp/raaviya-hr-demo_2026-10-27_13-53-13.zip \
  --database raaviya_history_removal_test \
  --port 1562
```

Replace the config path with the actual file you use for Odoo. Credentials are
read from that file; they are not command-line arguments. Run as your usual
Odoo OS user, without `sudo`.

The script creates a **new** database plus a separate filestore/config under:

```text
~/.local/share/raaviya-rehearsal/raaviya_history_removal_test/
```

It refuses the source database name, non-test names, existing databases,
existing output directories and the source HTTP port. It has no drop/overwrite
option. After an interrupted restore, retain the log/partial DB and choose a new
test name/directory for another attempt; never delete a database blindly.

Only known ZIP members are restored. SQL is run in PostgreSQL client restricted
mode. New pg_dump restrict/unrestrict bookends are replaced by the script's own
random restriction token; shell/reconnect commands remain prohibited.

The copied config retains your add-on paths, binds to localhost, uses port 1562,
selects only the new database and disables background cron. Mail connections,
queued emails and payment providers are disabled **in the copy**. Original ZIP,
config, source database and SaaS source/configuration are not edited. A new Odoo
copy UUID and local base URL are set. No SaaS hooks or neutralization scripts run
during restore. Starting/upgrading Odoo later loads installed modules normally;
the comparison below detects SaaS configuration changes rather than overwriting
or accepting them silently.

`baseline.json` contains saved payroll/review/punch data and hashes of SaaS tables
and SaaS parameter values. The output folder is private and the baseline/copied
config have mode 0600. Do not commit or share those credential/data files.

## 2. Merge the candidate into the local test checkout, then upgrade

Merge the reviewed History-removal code into your **local test checkout**. Before
upgrading, make sure no server is connected to the new test database. Keep live
deployment separate. Use the generated config, not the original one:

```sh
python3 /home/bambus/odoo/workspace/odoo_18/odoo-bin \
  -c "$HOME/.local/share/raaviya-rehearsal/raaviya_history_removal_test/odoo-test.conf" \
  -u bambus_hr_attendance_ot_fine,bambus_hr_daily_ops,attendance_custom_report,hr_payslip_excel_report \
  --stop-after-init
```

Use your actual `odoo-bin` location if different. The upgrade can stop for
duplicates, company mismatches or audited manual-only snapshots without real
punches. Review those records; do not bypass the migration guard.

## 3. Compare immediately, before manual test edits

```sh
python3 scripts/odoo_test_restore.py verify \
  --directory "$HOME/.local/share/raaviya-rehearsal/raaviya_history_removal_test"
```

This verifies saved payslip states/amounts/line IDs, decisions/exclusions/coverage,
punches and paid-day decisions against the baseline. It accepts the renamed
review model but requires the old History models to be absent. It also checks
the original config and SaaS configuration hashes. It does not compute salary,
approve anything or initiate payment. Zero-row counts are reported honestly:
an empty-payroll backup cannot demonstrate preservation of existing payslips.

If comparison fails, keep the evidence and investigate before manual changes.
Passing comparison verifies preservation only, not calculation accuracy or full
customer release readiness.

## 4. Start the local copy

```sh
python3 /home/bambus/odoo/workspace/odoo_18/odoo-bin \
  -c "$HOME/.local/share/raaviya-rehearsal/raaviya_history_removal_test/odoo-test.conf"
```

Open **http://localhost:1562** using your restored Odoo login. The script does not
change user passwords. Run one employee/date scenario at a time, starting with
the roster and actual punches, then calculation-type switching, approval/Ignore/
Cancel, draft payroll recomputation and both report downloads. Re-run salary
calculations only on disposable draft test payslips. A later baseline difference
after deliberate manual test edits is expected.

## Script verification

```sh
python3 -m unittest discover -s scripts/tests -v
```

Automated script validation covers source/non-test name rejection, traversal and
symlink rejection, literal credential parsing, pg_dump bookends and content
selection. A real isolated restore/filestore comparison, four-module upgrade,
baseline comparison, overwrite refusal and negative comparison checks are also
required when changing the restore workflow. This does not replace Odoo business
tests or installed browser testing with the customer's complete add-on source.

Validation recorded on 27 October 2026: all **7 script unit tests passed**; an
isolated restore of the available 06:10 staging backup restored **540 filestore
files byte-for-byte**, then the four-module upgrade and baseline comparison
passed. A separate saved-money fixture preserved **3 payslips, 6 salary lines,
15 punches and 3 reviews**. Existing database/directory refusals, detection of a
changed salary amount and blocking a psql shell meta-command also passed. SaaS
hashes and source config remained unchanged. The later 13:53 backup is still on
the user's computer and must be checked with this workflow locally.
