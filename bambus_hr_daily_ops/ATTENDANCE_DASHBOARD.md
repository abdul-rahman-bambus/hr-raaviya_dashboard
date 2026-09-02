# Attendance Dashboard — developer guide

## Product behaviour

`Attendance Dashboard` is the daily operational entry point. Its first phase is
the Attendance Metrics panel. It opens on the current date and current Odoo
company. Previous/next buttons and the date input reload every metric.

`Attendance History` intentionally retains the original Kanban/list/form action.
It is the record-oriented audit and administration view; do not remove it when
changing the dashboard.

The dashboard does **not** create or populate attendance sheets. Metrics are read
from the existing `bambus.hr.attendance.sheet` and its existing line entries for
the selected company/date. This intentionally produces the same totals as the
original sheet header. Attendance History remains available for record management.

## Technical flow

1. The client action tag `bambus_attendance_dashboard` mounts the OWL component.
2. The component calls `bambus.hr.attendance.sheet.get_attendance_dashboard` with
   an ISO `YYYY-MM-DD` date. The model name is only the RPC host; the method does
   not read or write attendance-sheet lines.
3. The model finds the existing sheet for the selected company/date and aggregates
   its existing lines. It does not call `action_generate_lines` or refresh lines.
4. Changing the date repeats the same read-only calculation. No create/write
   operation exists in the dashboard client action.

The parent sheet is first located with the current user's normal company and
record rules. Its lines are then read with `sudo()` only through that authorized
parent. This prevents unrelated global HR line rules from hiding valid historical
lines while still preventing access to a sheet outside the user's companies.
Client requests are sequenced so a slow response for an earlier date cannot
overwrite the latest selected date.

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
- **All / Present / Absent / Half Day / Leave** use the statuses already stored on
  the existing sheet lines, matching the original attendance-sheet counters.
- **Not Marked** counts existing absent sheet lines without a punch-in.
- **Punched In / Out** count sheet lines with an existing check-in/check-out.
- **Daily Work Entries** counts sheet lines linked to an attendance entry.
- **On Duty / Upcoming On Duty** remain zero until a source on-duty model is agreed.

## Manual acceptance checklist

1. Open Attendance Dashboard and confirm today's date is selected.
2. Navigate backward/forward and with the date picker; all sections must change.
3. Visit a date with an existing sheet and compare every metric with its header.
4. Confirm opening/changing dates does not create or modify any record.
5. Open Attendance History and confirm old Kanban/list/form records remain usable.
6. Switch active company and confirm that another company's entries are not shown.
