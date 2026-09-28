# Bambus HR Daily Ops

## Attendance automation templates

HR Managers maintain reusable rule masters under **HRMS > Configuration >
Automation Rules**. A template contains effective dates, late-entry and
early-exit grace periods, break allowance, minimum overtime, weekend/holiday
overtime, and the default calculation methods and rates.

A template can be assigned to multiple employees. Resolution is deliberately
simple: the employee template is used first; otherwise the employee's company
default template is used. Expired, future, inactive, or missing templates fall
back to the legacy company/contract settings. Shift start, end, and work periods
continue to come from the employee's work schedule, while employee-specific
wage and statutory rates continue to come from the contract.

The resolved template affects automatic detection and supplies defaults to the
HR update dialogs. The system proposes values; authorized HR users may correct
the hours, method, and rate before saving the final attendance result.

Overtime can start at shift end, after a configurable offset, or at a fixed
clock time. It can have no end, a fixed end time, or a maximum duration, with
exact-minute or block rounding. Half-day hours and full-day classification are
also template driven so schedules of different lengths remain valid full days.
Weekly-off and public-holiday policies are independent and can either suppress
overtime or propose every valid worked hour for HR review.

### Salary-based overtime rates

Set **OT Rate Policy** to **Salary Range / Slab** to derive the hourly overtime
rate from the contract salary valid for the attendance date. Monthly, daily,
and hourly contract values are supported as salary bases. Slabs use inclusive
lower and upper limits; an unchecked **Has Maximum** creates the final
open-ended range. Overlapping ranges and multiple open-ended slabs are rejected.

Example: `0–9,000 = 75/hour`, `9,000.01–12,000 = 100/hour`, and
`12,000.01–No Limit = 120/hour`. Saved entries keep a snapshot of the
template, salary basis, matched slab, rate, hours, and amount, so later contract
salary changes affect new proposals without changing historical saved updates.

Use **Assign Existing Employees** on the template to select active employees
from the template company. The assigned list is read-only and never creates an
employee; employee creation remains in the Employees workflow.

## Overtime and late/fine update flow

Attendance punches and the employee's work schedule produce proposed overtime
and late/fine hours.  These proposals do not become authoritative payroll
amounts until HR reviews and saves them.

1. The attendance engine calculates overtime and late/fine hours.
2. The daily attendance sheet marks the proposal as `Needs Review`.
3. HR opens **OT** or **Fine** for the employee and date.
4. The update dialog shows the system-calculated hours separately from the
   editable final hours.
5. HR selects a calculation method, adjusts the rate when applicable, reviews
   the automatically calculated amount, and clicks **Save Changes**.
6. Payroll uses the saved attendance-sheet hours and amount.

This is attendance maintenance, not a request/approval chain. Template
configuration remains restricted to HR managers, while authorized HR users can
correct and save daily attendance values.

### Calculation methods

| Method | Calculation |
| --- | --- |
| Fixed Amount | The entered amount is used once. |
| Fixed Amount per Hour | Final hours multiplied by the entered rate. |
| Half Day | Half of the employee's daily salary. |
| Full Day | The employee's daily salary. |
| Regularize | Zero payment or deduction. |
| 1x Salary | Final hours multiplied by the derived hourly salary. |
| 1.5x Salary | Final hours multiplied by 1.5 times hourly salary. |
| 2x Salary | Final hours multiplied by 2 times hourly salary. |

For hourly contracts, the configured hourly rate is used. For daily contracts,
the daily wage is divided by scheduled hours. For monthly contracts, daily pay
is monthly wage divided by 30 and hourly pay is that result divided by scheduled
hours. Existing contract overtime and late-fine rates provide the defaults for
fixed-per-hour updates.

### State meanings

- **No Exception**: no calculated value is awaiting review.
- **Needs Review**: the system has proposed hours for HR review.
- **Updated**: the HR-saved hours, method, rate, and amount are final
  for payroll.
- **Excluded**: the proposal must not affect payroll.

### Audit principle

The attendance calculation supplies a recommendation; the saved update stores
the HR correction. The update saves the selected method and rate
along with the final hours and amount so the payroll result can be explained
later.

## Testing

The automated suite creates isolated employees, contracts, schedules,
attendance punches, templates, salary slabs, and saved attendance records for
the main company-default and employee-override scenarios. See
[`TESTING_CHECKLIST.md`](TESTING_CHECKLIST.md) for automated coverage, expected
client examples, and the browser/UAT checks to complete before release.
