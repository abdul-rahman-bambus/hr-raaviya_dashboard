# Attendance Dashboard — developer guide

## Product behaviour

`Attendance Dashboard` is the daily operational entry point. Its first phase is
the Attendance Metrics panel. It opens on the current date and current Odoo
company. Previous/next buttons and the date input reload every metric.

`Attendance History` intentionally retains the original Kanban/list/form action.
It is the record-oriented audit and administration view; do not remove it when
changing the dashboard.

The dashboard does **not** create or populate attendance sheets. Metrics are read
directly from the employee roster, `hr.attendance` punches and approved `hr.leave`
entries. Attendance History remains available separately for record management.

## Technical flow

1. The client action tag `bambus_attendance_dashboard` mounts the OWL component.
2. The component calls `bambus.hr.attendance.sheet.get_attendance_dashboard` with
   an ISO `YYYY-MM-DD` date. The model is only the RPC host; the method does not
   read or write attendance-sheet lines.
3. The model loads active employees assigned to the current company plus shared
   employees whose company is unset, then reads attendance punches overlapping the
   selected local day and approved time off covering that date.
4. Changing the date repeats the same read-only calculation. No create/write
   operation exists in the dashboard client action.

Client requests are sequenced so a slow response for an earlier date cannot
overwrite the latest selected date. The server uses normal access and company
rules for employees, attendances and time off; it does not use `sudo()`.

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
- **All Staff** counts active current-company and shared employees.
- **Present** counts distinct employees with an attendance punch, excluding
  employees on full-day approved time off.
- **Absent / Not Marked** count roster employees without a punch or approved leave.
- **Half Day / Leave / Upcoming Leaves** come from approved `hr.leave` entries.
- **Punched In / Out** count distinct employees, not individual attendance rows.
- **Daily Work Entries** counts existing attendance rows for the selected day.
- **On Duty / Upcoming On Duty** remain zero until a source on-duty model is agreed.

## Manual acceptance checklist

1. Open Attendance Dashboard and confirm today's date is selected.
2. Navigate backward/forward and with the date picker; all sections must change.
3. Visit a historical date and compare metrics with its attendance and leave data.
4. Confirm opening/changing dates does not create or modify any record.
5. Open Attendance History and confirm old Kanban/list/form records remain usable.
6. Switch active company and confirm that another company's entries are not shown.
