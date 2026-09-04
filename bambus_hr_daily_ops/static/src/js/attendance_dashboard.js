/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AttendanceDashboard extends Component {
    static template = "bambus_hr_daily_ops.AttendanceDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: null,
            error: "",
            query: "",
            statusFilter: "all",
            currentPage: 1,
            pageSize: 10,
        });
        this.loadSequence = 0;
        onWillStart(() => this.load());
    }

    async load(date) {
        const sequence = ++this.loadSequence;
        this.state.loading = true;
        this.state.error = "";
        const selectedDate = date || this.state.data?.date || this.today();
        try {
            const data = await this.orm.call(
                "bambus.hr.attendance.sheet",
                "get_attendance_dashboard",
                [],
                { selected_date: selectedDate }
            );
            // A slower response for the previous date must never overwrite the
            // most recently selected date.
            if (sequence === this.loadSequence) {
                this.state.data = { ...data };
                this.state.currentPage = 1;
            }
        } catch (error) {
            if (sequence === this.loadSequence) {
                this.state.error = error.cause?.message || error.message || "Unable to load attendance.";
            }
        } finally {
            if (sequence === this.loadSequence) {
                this.state.loading = false;
            }
        }
    }

    today() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
    }

    formatHours(value) {
        const minutes = Math.round((value || 0) * 60);
        return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
    }

    metricValue(metric) {
        const value = this.state.data.metrics[metric[0]];
        return metric[3] === "hours" ? `${this.formatHours(value)} h` : value;
    }

    get filteredDailyEmployees() {
        const query = this.state.query.trim().toLowerCase();
        return (this.state.data?.daily_attendance || []).filter((employee) => {
            const matchesStatus = this.state.statusFilter === "all" || employee.status === this.state.statusFilter;
            const matchesQuery = !query || [employee.name, employee.department, employee.shift]
                .some((value) => value.toLowerCase().includes(query));
            return matchesStatus && matchesQuery;
        });
    }

    get pageCount() {
        return Math.max(1, Math.ceil(this.filteredDailyEmployees.length / this.state.pageSize));
    }

    get dailyEmployees() {
        const start = (this.state.currentPage - 1) * this.state.pageSize;
        return this.filteredDailyEmployees.slice(start, start + this.state.pageSize);
    }

    get firstVisibleEmployee() {
        return this.filteredDailyEmployees.length
            ? (this.state.currentPage - 1) * this.state.pageSize + 1
            : 0;
    }

    get lastVisibleEmployee() {
        return Math.min(
            this.state.currentPage * this.state.pageSize,
            this.filteredDailyEmployees.length
        );
    }

    updateQuery(ev) {
        this.state.query = ev.target.value;
        this.state.currentPage = 1;
    }

    updateStatusFilter(ev) {
        this.state.statusFilter = ev.target.value;
        this.state.currentPage = 1;
    }

    updatePageSize(ev) {
        this.state.pageSize = Number(ev.target.value);
        this.state.currentPage = 1;
    }

    goToPage(page) {
        this.state.currentPage = Math.min(Math.max(page, 1), this.pageCount);
    }

    fineDisplay(hours) {
        return hours > 0 ? `${this.formatHours(hours)} h` : "—";
    }

    downloadDailyAttendance() {
        const headers = ["Name", "Department", "Work Schedule", "Attendance", "In Time", "Out Time", "Fine Hours"];
        const rows = this.filteredDailyEmployees.map((employee) => [
            employee.name, employee.department, employee.shift, employee.status_label,
            employee.check_in, employee.check_out, this.fineDisplay(employee.fine_hours),
        ]);
        const csv = [headers, ...rows].map((row) => row.map((value) =>
            `"${String(value ?? "").replaceAll('"', '""')}"`
        ).join(",")).join("\n");
        const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `daily-attendance-${this.state.data.date}.csv`;
        link.click();
        URL.revokeObjectURL(url);
    }

    async changeDate(ev) {
        await this.load(ev.target.value);
    }

    moveDate(offset) {
        const date = new Date(`${this.state.data.date}T00:00:00Z`);
        date.setUTCDate(date.getUTCDate() + offset);
        this.load(date.toISOString().slice(0, 10));
    }

    openHistory() {
        this.action.doAction("bambus_hr_daily_ops.action_bambus_hr_attendance_sheet");
    }
}

registry.category("actions").add("bambus_attendance_dashboard", AttendanceDashboard);
