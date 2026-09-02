# Attendance Dashboard — developer guide

## Product behaviour

`Attendance Dashboard` is the daily operational entry point. Its first phase is
the Attendance Metrics panel. It opens on the current date and current Odoo
company. Previous/next buttons and the date input reload every metric.

`Attendance History` intentionally retains the original Kanban/list/form action.
It is the record-oriented audit and administration view; do not remove it when
changing the dashboard.

The dashboard does **not** create or populate attendance sheets. Metrics are read
directly from existing employees, `hr.attendance` punches and approved `hr.leave`
entries. Attendance History remains available separately for record management.

## Technical flow

1. The client action tag `bambus_attendance_dashboard` mounts the OWL component.
2. The component calls `bambus.hr.attendance.sheet.get_attendance_dashboard` with
   an ISO `YYYY-MM-DD` date. The model name is only the RPC host; the method does
   not read or write attendance-sheet lines.
3. The model converts the selected local day to UTC boundaries, reads source
   attendance/leave entries for active employees in the current company, and
   returns JSON-safe metrics.
4. Changing the date repeats the same read-only calculation. No create/write
   operation exists in the dashboard client action.

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
- **Present** means an employee has at least one overlapping attendance entry and
  is not on full-day approved leave.
- **Absent / Not Marked** means an active employee has no attendance and no
  approved full- or half-day leave. They intentionally match in this first phase.
- **Punched In / Out** count distinct employees, not individual punch rows.
- **Daily Work Entries** currently reports the number of existing attendance rows.
- **On Duty / Upcoming On Duty** remain zero until a source on-duty model is agreed.

## Manual acceptance checklist

1. Open Attendance Dashboard and confirm today's date is selected.
2. Navigate backward/forward and with the date picker; all sections must change.
3. Visit a date without a sheet and confirm metrics still load from source entries.
4. Confirm opening/changing dates does not create or modify any record.
5. Open Attendance History and confirm old Kanban/list/form records remain usable.
6. Switch active company and confirm that another company's entries are not shown.
