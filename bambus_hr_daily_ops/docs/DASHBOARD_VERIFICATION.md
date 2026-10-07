# Dashboard updates without a full refresh

Attendance Dashboard, Attendance Editor, Employee Attendance, and Employee Dashboard
keep their existing content mounted while fetching new data. A small Updating indicator
appears during background requests. Failed requests keep the previous data visible with
an error and retry button. Initial loading still shows a loading message.

Date and month navigation uses the requested period immediately, so consecutive arrow
clicks advance correctly even on a slow connection. Only the latest request can update
the screen. Search, filters, collapsed groups, and the calendar/daily tab remain selected.
Same-day refreshes preserve pagination (clamped if fewer pages remain); changing day
starts at page one. Attendance edits still save automatically. Date navigation waits
for active saves and adjustment dialogs to finish, and previous-day rows cannot be
edited while a new day is loading. Delayed leave/adjustment responses cannot update a
new day's data.

The HRMS overview's graph filters and Attendance Location Map already update in place;
their handlers do not reload the client action or remove their dashboard/map container.

## Automated browser checks

These tests mount the production JavaScript and XML templates with Odoo 18's OWL library
in Chromium. ORM/action services are mocked to control slow, failed, and out-of-order
responses. Backend behavior is covered separately by the existing Odoo test suite.

```sh
python -m pip install playwright
# Chromium must be installed; override its path with CHROMIUM_BIN if needed.
ODOO_SOURCE=/path/to/odoo python -m unittest discover \
  -s bambus_hr_daily_ops/tests/browser -v
```

Coverage includes persistent DOM nodes and focus, preserved filters and page state,
rapid date/month navigation, retry after failure, inline time autosave, correct save
dates, disabled edits during a date transition, and stale leave/adjustment responses.

## Quick UI verification

1. Open Attendance Dashboard or Attendance Editor. Select a filter and type a search.
2. Change the date. The metrics/list remain visible with Updating; only their data changes.
3. Click Next Day twice quickly. The picker advances twice and settles on the latest day.
4. Edit a punch time in Attendance Editor. The row remains visible and saves automatically.
5. Open Employee Attendance, choose Calendar View, and change month. Calendar View stays selected.
6. Simulate a failed request with browser network tools. Existing content remains visible;
   the error labels its loaded date/month. Retry fetches the requested period.

Upgrade `bambus_hr_daily_ops` to load the updated assets in an existing installation.
