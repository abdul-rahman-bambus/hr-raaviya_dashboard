/** @odoo-module **/

import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { AttendanceDashboard } from "./attendance_dashboard";

export class AttendanceEditor extends AttendanceDashboard {
    static template = "bambus_hr_daily_ops.AttendanceEditor";

    setup() {
        super.setup();
        this.notification = useService("notification");
        this.state.savingIds = {};
        this.state.logEmployee = null;
    }

    get filteredDailyGroups() {
        const groups = new Map();
        for (const employee of this.filteredDailyEmployees) {
            const name = employee.department || "No Department";
            if (!groups.has(name)) {
                groups.set(name, { id: name, name, employees: [] });
            }
            groups.get(name).employees.push(employee);
        }
        return [...groups.values()].sort((left, right) => left.name.localeCompare(right.name));
    }

    async updateEmployeeField(employee, field, event) {
        if (this.state.savingIds[employee.id]) {
            return;
        }
        const previousStatus = employee.status;
        const previousValue = employee[field];
        employee[field] = event.target.value;
        if (employee.status === "not_marked" && event.target.value) {
            employee.status = "present";
            employee.status_label = "Present";
        }
        await this.saveEmployee(employee, { previousStatus, field, previousValue });
    }

    async setStatus(employee, status) {
        if (this.state.savingIds[employee.id]) {
            return;
        }
        const previousStatus = employee.status;
        employee.status = status;
        employee.status_label = {
            present: "Present", absent: "Absent", halfday: "Half Day", leave: "Leave",
        }[status];
        await this.saveEmployee(employee, { previousStatus });
    }

    applyStatusTransition(employee, previousStatus, nextStatus) {
        if (!this.state.data || previousStatus === nextStatus) {
            return;
        }
        const updateCounter = (record) => {
            if (previousStatus && previousStatus in record) {
                record[previousStatus] = Math.max(0, (record[previousStatus] || 0) - 1);
            }
            if (nextStatus && nextStatus in record) {
                record[nextStatus] = (record[nextStatus] || 0) + 1;
            }
        };
        updateCounter(this.state.data.metrics);
        const department = this.state.data.departments?.find((item) => item.name === employee.department);
        const shift = this.state.data.shifts?.find((item) => item.name === employee.shift);
        if (department) {
            updateCounter(department);
        }
        if (shift) {
            updateCounter(shift);
        }
    }

    async createHalfDayLeave(employee) {
        if (employee.status === "halfday" || (employee.leave_id && employee.leave_is_half_day)) {
            await this.revokeStatus(employee, "halfday");
            return;
        }
        if (this.state.savingIds[employee.id]) {
            return;
        }
        this.state.savingIds[employee.id] = true;
        try {
            const result = await this.orm.call(
                "bambus.hr.attendance.sheet",
                "create_half_day_leave",
                [employee.id, this.state.data.date]
            );
            const previousStatus = employee.status;
            employee.leave_id = result.leave_id;
            employee.leave_is_half_day = true;
            employee.status = "halfday";
            employee.status_label = "Half Day";
            this.applyStatusTransition(employee, previousStatus, "halfday");
            this.notification.add(`${employee.name} half-day leave created and confirmed.`, {
                type: "success",
            });
        } catch (error) {
            this.notification.add(error.cause?.message || error.message || "Unable to create half-day leave.", {
                type: "danger",
            });
        } finally {
            this.state.savingIds[employee.id] = false;
        }
    }

    async toggleAbsent(employee) {
        if (employee.status === "absent") {
            await this.revokeStatus(employee, "absent");
            return;
        }
        await this.setStatus(employee, "absent");
    }

    async toggleLeave(employee) {
        if (employee.status === "leave" || (employee.leave_id && !employee.leave_is_half_day)) {
            await this.revokeStatus(employee, "leave");
            return;
        }
        this.openLeave(employee);
    }

    async revokeStatus(employee, status) {
        if (this.state.savingIds[employee.id]) {
            return;
        }
        this.state.savingIds[employee.id] = true;
        try {
            await this.orm.call(
                "bambus.hr.attendance.sheet",
                "revoke_dashboard_status",
                [employee.id, this.state.data.date, status]
            );
            const previousStatus = employee.status;
            const nextStatus = employee.has_attendance ? "present" : "not_marked";
            employee.status = nextStatus;
            employee.status_label = nextStatus === "present" ? "Present" : "Not Marked";
            employee.leave_id = false;
            employee.leave_is_half_day = false;
            employee.line_id = false;
            this.applyStatusTransition(employee, previousStatus, nextStatus);
            this.notification.add(`${employee.name} ${status === "absent" ? "absence" : "leave"} revoked.`, {
                type: "success",
            });
        } catch (error) {
            this.notification.add(error.cause?.message || error.message || "Unable to revoke status.", {
                type: "danger",
            });
        } finally {
            this.state.savingIds[employee.id] = false;
        }
    }

    openLeave(employee) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: employee.leave_id ? "Time Off" : "New Time Off Request",
            res_model: "hr.leave",
            res_id: employee.leave_id || false,
            views: [[false, "form"]],
            target: "new",
            context: {
                default_employee_id: employee.id,
                default_holiday_type: "employee",
                default_request_date_from: this.state.data.date,
                default_request_date_to: this.state.data.date,
            },
        }, {
            onClose: () => this.syncEmployee(employee),
        });
    }

    async syncEmployee(employee) {
        try {
            const data = await this.orm.call(
                "bambus.hr.attendance.sheet",
                "get_attendance_dashboard",
                [],
                { selected_date: this.state.data.date }
            );
            const updatedEmployee = data.daily_attendance.find((item) => item.id === employee.id);
            if (updatedEmployee) {
                Object.assign(employee, updatedEmployee);
            }
            this.state.data.metrics = data.metrics;
            this.state.data.departments = data.departments;
            this.state.data.shifts = data.shifts;
        } catch (error) {
            this.notification.add(error.cause?.message || error.message || "Unable to refresh attendance.", {
                type: "danger",
            });
        }
    }

    openLogs(employee) {
        this.state.logEmployee = employee;
    }

    closeLogs() {
        this.state.logEmployee = null;
    }

    async saveEmployee(employee, rollback = {}) {
        if (this.state.savingIds[employee.id]) {
            return;
        }
        this.state.savingIds[employee.id] = true;
        try {
            const result = await this.orm.call(
                "bambus.hr.attendance.sheet",
                "update_dashboard_attendance",
                [employee.id, this.state.data.date, {
                    status: employee.status,
                    check_in: employee.check_in_value || false,
                    check_out: employee.check_out_value || false,
                }]
            );
            employee.line_id = result.line_id;
            employee.worked_hours = result.worked_hours;
            this.applyStatusTransition(employee, rollback.previousStatus, result.status);
            this.notification.add(`${employee.name} attendance saved automatically.`, { type: "success" });
        } catch (error) {
            if (rollback.previousStatus) {
                employee.status = rollback.previousStatus;
                employee.status_label = {
                    present: "Present", absent: "Absent", halfday: "Half Day",
                    leave: "Leave", not_marked: "Not Marked",
                }[rollback.previousStatus];
            }
            if (rollback.field) {
                employee[rollback.field] = rollback.previousValue;
            }
            this.notification.add(error.cause?.message || error.message || "Unable to update attendance.", {
                type: "danger",
            });
        } finally {
            this.state.savingIds[employee.id] = false;
        }
    }

    isSaving(employeeId) {
        return Boolean(this.state.savingIds[employeeId]);
    }
}

registry.category("actions").add("bambus_attendance_editor", AttendanceEditor);
