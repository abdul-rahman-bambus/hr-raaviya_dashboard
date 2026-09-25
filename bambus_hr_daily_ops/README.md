# Bambus HR Daily Ops

## Attendance automation templates

HR Managers maintain reusable rule masters under **HRMS > Configuration >
Automation Rules**. A template contains effective dates, late-entry and
early-exit grace periods, break allowance, minimum overtime, weekend/holiday
overtime, and the default approval calculation methods and rates.

A template can be assigned to multiple employees. Resolution is deliberately
simple: the employee template is used first; otherwise the employee's company
default template is used. Expired, future, inactive, or missing templates fall
back to the legacy company/contract settings. Shift start, end, and work periods
continue to come from the employee's work schedule, while employee-specific
wage and statutory rates continue to come from the contract.

The resolved template affects automatic detection and supplies defaults to the
approval dialogs. It does not bypass HR approval.

### Salary-based overtime rates

Set **OT Rate Policy** to **Salary Range / Slab** to derive the hourly overtime
rate from the contract salary valid for the attendance date. Monthly, daily,
and hourly contract values are supported as salary bases. Slabs use inclusive
lower and upper limits; an unchecked **Has Maximum** creates the final
open-ended range. Overlapping ranges and multiple open-ended slabs are rejected.

Example: `0–9,000 = 75/hour`, `9,000.01–12,000 = 100/hour`, and
`12,000.01–No Limit = 120/hour`. Approved entries keep a snapshot of the
template, salary basis, matched slab, rate, hours, and amount, so later contract
salary changes affect new proposals without changing historical approvals.

Use **Assign Existing Employees** on the template to select active employees
from the template company. The assigned list is read-only and never creates an
employee; employee creation remains in the Employees workflow.

## Overtime and late/fine approval flow

Attendance punches and the employee's work schedule produce proposed overtime
and late/fine hours.  These proposals do not become authoritative payroll
amounts until an HR manager reviews them.

1. The attendance engine calculates overtime and late/fine hours.
2. The daily attendance sheet stores the proposal with a `Submitted` state.
3. HR opens **OT** or **Fine** for the employee and date.
4. The approval dialog shows the system-calculated hours separately from the
   editable approved hours.
5. HR selects a calculation method, confirms the rate when applicable, reviews
   the calculated amount, and approves the result.
6. Payroll uses the approved attendance-sheet hours and amount.  If no approved
   result exists, the original attendance calculation remains the fallback.

Only members of the HR Manager group can approve overtime or fines. Approved
attendance days remain protected by the existing attendance-sheet controls.

### Calculation methods

| Method | Calculation |
| --- | --- |
| Fixed Amount | The entered amount is used once. |
| Fixed Amount per Hour | Approved hours multiplied by the entered rate. |
| Half Day | Half of the employee's daily salary. |
| Full Day | The employee's daily salary. |
| Regularize | Zero payment or deduction. |
| 1x Salary | Approved hours multiplied by the derived hourly salary. |
| 1.5x Salary | Approved hours multiplied by 1.5 times hourly salary. |
| 2x Salary | Approved hours multiplied by 2 times hourly salary. |

For hourly contracts, the configured hourly rate is used. For daily contracts,
the daily wage is divided by scheduled hours. For monthly contracts, daily pay
is monthly wage divided by 30 and hourly pay is that result divided by scheduled
hours. Existing contract overtime and late-fine rates provide the defaults for
fixed-per-hour approvals.

### State meanings

- **Draft**: no calculated value is awaiting approval.
- **Submitted**: the system or HR has proposed hours for review.
- **Approved**: the manager-confirmed hours, method, rate, and amount are final
  for payroll.
- **Rejected**: the proposal must not affect payroll.

### Audit principle

The attendance calculation supplies a recommendation; the approval record
stores the managerial decision. The approval saves the selected method and rate
along with the final hours and amount so the payroll result can be explained
later.

## Testing

The automated suite creates isolated employees, contracts, schedules,
attendance punches, templates, salary slabs, and approval records for the main
company-default and employee-override scenarios. See
[`TESTING_CHECKLIST.md`](TESTING_CHECKLIST.md) for automated coverage, expected
client examples, and the browser/UAT checks to complete before release.
