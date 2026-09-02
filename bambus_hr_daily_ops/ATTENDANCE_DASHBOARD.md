# Attendance Dashboard — developer guide

## Product behaviour

`Attendance Dashboard` is the daily operational entry point. It opens on the
current date and current Odoo company. Previous/next buttons and the date input
reload every metric, grouping and employee row for the selected date.

`Attendance History` intentionally retains the original Kanban/list/form action.
It is the record-oriented audit and administration view; do not remove it when
changing the dashboard.

The dashboard does **not** create a sheet merely because a user visits a date.
When no record exists, it shows an empty state and an explicit create button.
The database constraint remains the authority for one sheet per company/date.

## Technical flow

1. The client action tag `bambus_attendance_dashboard` mounts the OWL component.
2. The component calls `bambus.hr.attendance.sheet.get_attendance_dashboard` with
   an ISO `YYYY-MM-DD` date.
3. The model searches only the active company and selected date, then returns a
   JSON-safe snapshot containing metrics, department/shift groups and employees.
4. Search is client-side because all rows for the single daily sheet are already
   loaded. Attendance modifications continue in the existing sheet form opened
   by **Manage Attendance**.

## Files and extension points

- `models/hr_attendance_sheet.py`: data contract and aggregation.
- `static/src/js/attendance_dashboard.js`: date state, RPC and navigation.
- `static/src/xml/attendance_dashboard.xml`: dashboard structure.
- `static/src/css/attendance_dashboard.css`: responsive presentation.
- `views/hr_attendance_sheet_views.xml`: dashboard/history actions and menus.

When adding a metric, add it to the model response first and then render it in the
template. Keep the RPC read-only. Any new write operation should use a named model
action so access rules, approval locking and audit behaviour remain server-side.

## Intentional definitions

- **Leave** counts full-day leave; half days have their own metric.
- **Not Marked** means absent with no punch-in.
- **Shift** uses the line contract's working schedule (`resource_calendar_id`),
  falling back to `No Shift`.
- Times are formatted in the current user's timezone by the existing line helper.

## Manual acceptance checklist

1. Open Attendance Dashboard and confirm today's date is selected.
2. Navigate backward/forward and with the date picker; all sections must change.
3. Visit a date without a sheet; no record should be silently created.
4. Create the missing sheet, load staff, and return to confirm the data appears.
5. Open Manage Attendance and confirm the existing workflow/actions still work.
6. Open Attendance History and confirm old Kanban/list/form records remain usable.
7. Switch active company and confirm that another company's sheet is not exposed.
