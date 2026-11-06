/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class EmployeeAttendance extends Component {
    static template = "bambus_hr_daily_ops.EmployeeAttendance";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const actionEmployeeId = this.props.action.params?.employee_id ||
            this.props.action.context?.active_id;
        if (actionEmployeeId) {
            window.sessionStorage.setItem("bambus_employee_attendance_id", String(actionEmployeeId));
        }
        this.employeeId = Number(
            actionEmployeeId || window.sessionStorage.getItem("bambus_employee_attendance_id")
        ) || false;
        this.state = useState({
            loading: true,
            error: "",
            data: null,
            selectedMonth: "",
            selectedDay: null,
            activeView: "daily",
        });
        this.loadSequence = 0;
        onWillStart(() => this.load());
    }

    async load(month) {
        const selectedMonth = month || this.state.selectedMonth || false;
        const sequence = ++this.loadSequence;
        this.state.selectedMonth = selectedMonth || "";
        this.state.loading = true;
        this.state.error = "";
        try {
            if (!this.employeeId) {
                throw new Error("No employee was selected. Return to Employees and open Attendance again.");
            }
            const data = await this.orm.silent.call(
                "hr.employee", "get_monthly_attendance", [this.employeeId, selectedMonth]
            );
            if (sequence === this.loadSequence) {
                if (data.month !== this.state.data?.month) this.state.selectedDay = null;
                this.state.data = data;
                this.state.selectedMonth = data.month;
            }
        } catch (error) {
            if (sequence === this.loadSequence) {
                this.state.error = error.cause?.message || error.message || "Unable to load attendance.";
            }
        } finally {
            if (sequence === this.loadSequence) this.state.loading = false;
        }
    }

    changeMonth(event) {
        if (event.target.value) this.load(event.target.value);
    }

    moveMonth(offset) {
        const date = new Date(`${this.state.selectedMonth}-01T00:00:00Z`);
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

    get calendarWeeks() {
        if (!this.state.data) {
            return [];
        }
        const [year, month] = this.state.data.month.split("-").map(Number);
        const firstDay = new Date(Date.UTC(year, month - 1, 1));
        const lastDay = new Date(Date.UTC(year, month, 0));
        const gridStart = new Date(firstDay);
        gridStart.setUTCDate(gridStart.getUTCDate() - gridStart.getUTCDay());
        const gridEnd = new Date(lastDay);
        gridEnd.setUTCDate(gridEnd.getUTCDate() + (6 - gridEnd.getUTCDay()));
        const rowsByDate = new Map(this.state.data.rows.map((row) => [row.date, row]));
        const weeks = [];
        let week = [];
        for (const cursor = new Date(gridStart); cursor <= gridEnd; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
            const key = cursor.toISOString().slice(0, 10);
            const row = rowsByDate.get(key) || null;
            week.push({
                key,
                number: cursor.getUTCDate(),
                inMonth: cursor.getUTCMonth() === month - 1,
                row,
                status: row?.status || "not_marked",
                statusLabel: row?.status_label || "Not Marked",
            });
            if (week.length === 7) {
                weeks.push(week);
                week = [];
            }
        }
        return weeks;
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

    reviewLabel(state) {
        return {submitted: _t("Needs Review"), approved: _t("Approved"), rejected: _t("Excluded")}[state] || "";
    }

    checkoutLabel(row) {
        if (!row.check_out || !row.check_out_day_offset) return row.check_out || _t("Punched In");
        return _t("%s (+%s day)", row.check_out, row.check_out_day_offset);
    }

    statusShort(status) {
        return {present: "P", absent: "A", halfday: "HD", leave: "L",
            paid_weekly_off: "WO", unpaid_weekly_off: "WO",
            paid_public_holiday: "PH", unpaid_public_holiday: "PH"}[status] || "";
    }

    openDailyDashboard(row) {
        if (!this.state.data.can_manage_attendance) return;
        return this.action.doAction({
            type: "ir.actions.client", tag: "bambus_attendance_editor",
            params: {selected_date: row.date, filter_employee_id: this.employeeId,
                employee_query: this.state.data.employee.name},
        });
    }

    downloadReport() {
        const rows = this.state.data.rows.map((row) => [
            row.date, row.status_label, row.check_in, row.check_out,
            this.formatHours(row.worked_hours), this.formatHours(row.overtime_hours),
            this.formatHours(row.fine_hours), row.check_out_date || "",
        ]);
        const csv = [["Date", "Status", "Check In", "Check Out", "Worked Hours", "Overtime", "Fine", "Check Out Date"], ...rows]
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
