/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class EmployeeAttendance extends Component {
    static template = "bambus_hr_daily_ops.EmployeeAttendance";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.employeeId = this.props.action.params.employee_id;
        this.state = useState({ loading: true, error: "", data: null, selectedDay: null });
        onWillStart(() => this.load());
    }

    async load(month) {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.orm.call(
                "hr.employee",
                "get_monthly_attendance",
                [],
                { employee_id: this.employeeId, month }
            );
        } catch (error) {
            this.state.error = error.cause?.message || error.message || "Unable to load attendance.";
        } finally {
            this.state.loading = false;
        }
    }

    changeMonth(event) {
        this.load(event.target.value);
    }

    moveMonth(offset) {
        const date = new Date(`${this.state.data.month}-01T00:00:00Z`);
        date.setUTCMonth(date.getUTCMonth() + offset);
        this.load(date.toISOString().slice(0, 7));
    }

    formatDate(value) {
        const date = new Date(`${value}T00:00:00`);
        return new Intl.DateTimeFormat(undefined, {
            day: "2-digit", month: "short", weekday: "short",
        }).format(date);
    }

    formatHours(value) {
        const minutes = Math.round((value || 0) * 60);
        return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
    }

    goBack() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            res_id: this.employeeId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openLogs(row) {
        this.state.selectedDay = row;
    }

    closeLogs() {
        this.state.selectedDay = null;
    }

    downloadReport() {
        const rows = this.state.data.rows.map((row) => [
            row.date, row.status_label, row.check_in, row.check_out,
            this.formatHours(row.worked_hours), this.formatHours(row.overtime_hours),
            this.formatHours(row.fine_hours),
        ]);
        const csv = [["Date", "Status", "Check In", "Check Out", "Worked Hours", "Overtime", "Fine"], ...rows]
            .map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(","))
            .join("\n");
        const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `${this.state.data.employee.name}-${this.state.data.month}-attendance.csv`;
        link.click();
        URL.revokeObjectURL(url);
    }
}

registry.category("actions").add("bambus_employee_attendance", EmployeeAttendance);
