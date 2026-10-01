# Attendance Automation — Simple User Guide

This guide explains how HR can configure late arrival, early leaving, breaks,
overtime, rates, and fines. The system **proposes** a result. HR reviews and
saves the final value before payroll uses it.

## 1. Show Automation Rules

Automation Rules are available in developer mode.

1. Open **Settings**.
2. Select **Activate Developer Mode**.
3. Return to **HRMS**.
4. Open **Configuration → Automation Rules**.

You may also add `?debug=1` after `/web` in the browser address.

## 2. Create a template

Select **New**, enter a clear name, select the company, and enter the effective
period. An employee-specific template has priority over the company default.
An inactive, future, or expired template is ignored.

## 3. Late & Early Exit

| Option | Simple meaning | Example |
| --- | --- | --- |
| Late Entry Rule | Detect arrival after shift start. | Shift starts 09:00 and arrival is 09:12. |
| Late Entry Grace | Free minutes before a fine begins. | With 5 minutes grace, 09:04 has no fine; 09:12 produces 7 fine minutes. |
| Early Exit Rule | Detect leaving before shift end. | Shift ends 17:00 and departure is 16:45. |
| Early Exit Grace | Free early-leaving minutes. | With 5 minutes grace, leaving at 16:57 has no fine. |
| Fine Calculation Type | How the deduction amount is calculated. | Per-minute salary uses daily salary divided by scheduled minutes. |

## 4. Breaks

Enable **Break Rule** and enter **Allowed Break (Minutes)**. Only break time
above the allowance becomes a fine. Example: a 60-minute break with a
45-minute allowance produces 15 fine minutes.

## 5. Overtime

| Option | Meaning |
| --- | --- |
| Overtime Rule | Enables automatic OT proposals. |
| Minimum Overtime | OT below this number is ignored. The boundary is inclusive. |
| Weekly Off/Public Holiday Policy | `Not Payable` gives zero; `All Worked Hours` proposes every worked hour. |
| Start: At Shift End | OT begins when the assigned shift ends. |
| Start: Minutes After Shift End | OT begins after the entered waiting period. |
| Start: Fixed Time | OT begins at the entered clock time. |
| End: No Limit | Uses all eligible time. |
| End: Fixed Time | Stops OT at the entered clock time. |
| End: Maximum Duration | Caps OT to the entered number of minutes. |
| Rounding | Rounds eligible OT down to exact, 15, 30, or 60-minute blocks. |

Example: shift ends at 17:00, start offset is 15 minutes, maximum OT is 60
minutes, and checkout is 20:00. Eligible OT is 17:15–18:15 = **60 minutes**.

## 6. Rates and salary slabs

- **Fixed Template Rate:** uses one rate from the template.
- **Salary Range / Slab:** chooses a rate using monthly, daily, or hourly salary.
- **Salary Multiplier:** the review method can pay 1x, 1.5x, or 2x hourly salary.

Slabs cannot overlap. Leave **Has Maximum** unchecked only on the last,
open-ended slab.

## 7. Calculation methods

| Method | Result |
| --- | --- |
| Fixed Amount | One entered amount. |
| Fixed Amount per Hour | Hours × entered rate. |
| Half Day | Half of daily salary. |
| Full Day | One daily salary. |
| Regularize | Zero amount. |
| 1x / 1.5x / 2x Salary | Hours × hourly salary × multiplier. |
| Per Minute from Daily Salary (fine) | Fine minutes × daily salary ÷ scheduled minutes. |

For monthly salary ₹12,000, daily salary is ₹400. With 480 scheduled minutes,
the minute rate is ₹0.833333. A 12-minute fine is ₹10.00.

## 8. Assign and review

1. Assign the template to employees, or set it as the company default.
2. Create/import attendance punches.
3. Open **Attendance** for the required date.
4. Select the **Overtime Hours** or **Late / Fine Hours** card to filter people.
5. Select **OT** or **Fine** on an employee row.
6. Compare system-calculated hours with final hours.
7. Check the rate and amount, then select **Save Changes**.

Payroll uses the saved HR result. Later salary or template changes do not change
an already saved snapshot.

## 9. Common problems

- **Automation Rules are missing:** enable developer mode.
- **No OT:** check template dates, OT switch, minimum, window, schedule, and checkout.
- **No fine:** check late/early/break switches and grace/allowance.
- **No slab rate:** make sure salary falls inside exactly one slab.
- **Old browser behavior:** upgrade the module, restart Odoo, and hard-refresh.

For step-by-step verification, use [Manual Testing](ATTENDANCE_AUTOMATION_MANUAL_TESTING.md).
