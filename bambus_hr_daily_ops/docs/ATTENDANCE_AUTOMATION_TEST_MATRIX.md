# Attendance Automation — Automated Coverage Matrix

This matrix connects configuration choices to automated tests. Automated tests
create their own employees, contracts, schedules, templates, punches, review
records, and salary slabs; they do not depend on demo data.

| Area | Options/boundaries covered | Automated test |
| --- | --- | --- |
| Resolution | employee, company, expired fallback | `test_employee_template_overrides_company_detection_rules`, `test_expired_employee_template_falls_back_to_company_default` |
| Enable switches | late, early, break and OT disabled | `test_disabled_rules_clear_overtime_and_late_fine` |
| Grace and salary-minute fine | late beyond grace; exact expected amount | `test_company_default_calculates_overtime_late_and_fine` |
| Minimum OT | one minute below and exact boundary | `test_minimum_overtime_is_inclusive_at_sixty_minutes` |
| Fixed OT window | before start, inside window, capped at end | `test_fixed_overtime_window_uses_exact_minutes_and_caps_at_end` |
| Rounding | exact, 15, 30 and 60 minutes | `test_every_overtime_rounding_option` |
| Weekly off | all worked hours | `test_weekly_off_policy_proposes_all_worked_hours` |
| Public holiday | all worked hours | `test_public_holiday_policy_proposes_all_worked_hours` |
| Rate policy | contract, fixed template and salary slab | `test_fixed_contract_and_slab_rate_policies` |
| Salary slabs | lower, middle, open ended | `test_salary_slabs_drive_saved_update_after_detection` |
| OT methods | fixed, hourly, half/full day, regularize, 1x/1.5x/2x | `test_every_overtime_calculation_option` |
| Fine methods | all OT methods plus salary per minute | `test_every_fine_calculation_option` |
| Snapshot | salary change does not change saved value | `test_salary_change_keeps_saved_snapshot` |
| Dashboard review | detected values and saved OT/fine amounts | `test_dashboard_review_opens_detected_values_and_saves_snapshots` |
| Attendances visibility | approved daily values appear once on the final punch | `test_attendance_list_shows_approved_daily_values_once` |

The manual guide additionally covers UI visibility, disabled special-day policies,
break boundaries, fixed/offset/duration windows, dashboard filtering, and payroll
screens. These remain browser/UAT checks even when the underlying calculation is
covered by a transaction test.
