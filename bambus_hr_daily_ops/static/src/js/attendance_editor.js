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
    }

    updateEmployeeField(employee, field, event) {
        employee[field] = event.target.value;
    }

    async setStatus(employee, status) {
        employee.status = status;
        employee.status_label = {
            present: "Present", absent: "Absent", halfday: "Half Day", leave: "Leave",
        }[status];
        await this.saveEmployee(employee);
    }

    async saveEmployee(employee) {
        if (this.state.savingIds[employee.id]) {
            return;
        }
        this.state.savingIds[employee.id] = true;
        try {
            await this.orm.call(
                "bambus.hr.attendance.sheet",
                "update_dashboard_attendance",
                [employee.id, this.state.data.date, {
                    status: employee.status === "not_marked" ? "absent" : employee.status,
                    check_in: employee.check_in_value || false,
                    check_out: employee.check_out_value || false,
                    overtime_hours: Number(employee.overtime_hours) || 0,
                    fine_hours: Number(employee.fine_hours) || 0,
                }]
            );
            this.notification.add(`${employee.name} attendance updated.`, { type: "success" });
            await this.load(this.state.data.date);
        } catch (error) {
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
