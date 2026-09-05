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
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            data: null,
            error: "",
            query: "",
            statusFilter: "all",
            currentPage: 1,
            pageSize: 10,
            collapsedContractTypes: {},
            savingIds: {},
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
            const matchesQuery = !query || [
                employee.name,
                employee.department,
                employee.shift,
                employee.contract_type,
            ].some((value) => (value || "").toLowerCase().includes(query));
            return matchesStatus && matchesQuery;
        });
    }

    get filteredDailyGroups() {
        const groups = new Map();
        for (const employee of this.filteredDailyEmployees) {
            const id = employee.contract_type_id || 0;
            if (!groups.has(id)) {
                groups.set(id, {
                    id,
                    name: employee.contract_type,
                    employees: [],
                });
            }
            groups.get(id).employees.push(employee);
        }
        return [...groups.values()].sort((left, right) => {
            if (!left.id) {
                return 1;
            }
            if (!right.id) {
                return -1;
            }
            return left.name.localeCompare(right.name);
        });
    }

    get dailyGroupPages() {
        const pages = [];
        let page = [];
        let employeeCount = 0;
        for (const group of this.filteredDailyGroups) {
            if (page.length && employeeCount + group.employees.length > this.state.pageSize) {
                pages.push(page);
                page = [];
                employeeCount = 0;
            }
            page.push(group);
            employeeCount += group.employees.length;
        }
        if (page.length) {
            pages.push(page);
        }
        return pages;
    }

    get pageCount() {
        return Math.max(1, this.dailyGroupPages.length);
    }

    get dailyGroups() {
        return this.dailyGroupPages[this.state.currentPage - 1] || [];
    }

    get dailyEmployees() {
        return this.dailyGroups.flatMap((group) => group.employees);
    }

    get firstVisibleEmployee() {
        if (!this.filteredDailyEmployees.length) {
            return 0;
        }
        const previousEmployeeCount = this.dailyGroupPages
            .slice(0, this.state.currentPage - 1)
            .reduce(
                (count, page) => count + page.reduce(
                    (pageCount, group) => pageCount + group.employees.length,
                    0
                ),
                0
            );
        return previousEmployeeCount + 1;
    }

    get lastVisibleEmployee() {
        return this.firstVisibleEmployee + this.dailyEmployees.length - (this.dailyEmployees.length ? 1 : 0);
    }

    get dashboardPageCount() {
        return Math.max(1, Math.ceil(this.filteredDailyEmployees.length / this.state.pageSize));
    }

    get dashboardEmployees() {
        const start = (this.state.currentPage - 1) * this.state.pageSize;
        return this.filteredDailyEmployees.slice(start, start + this.state.pageSize);
    }

    get dashboardFirstVisibleEmployee() {
        return this.filteredDailyEmployees.length ?
            (this.state.currentPage - 1) * this.state.pageSize + 1 : 0;
    }

    get dashboardLastVisibleEmployee() {
        return this.dashboardFirstVisibleEmployee + this.dashboardEmployees.length -
            (this.dashboardEmployees.length ? 1 : 0);
    }

    goToDashboardPage(page) {
        this.state.currentPage = Math.min(Math.max(page, 1), this.dashboardPageCount);
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

    toggleContractType(contractTypeId) {
        this.state.collapsedContractTypes[contractTypeId] =
            !this.state.collapsedContractTypes[contractTypeId];
    }

    isContractTypeCollapsed(contractTypeId) {
        return Boolean(this.state.collapsedContractTypes[contractTypeId]);
    }

    fineDisplay(hours) {
        return hours > 0 ? `${this.formatHours(hours)} h` : "—";
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

    downloadDailyAttendance() {
        const headers = ["Name", "Contract Type", "Department", "Work Schedule", "Attendance", "In Time", "Out Time", "Fine Hours"];
        const rows = this.filteredDailyGroups.flatMap((group) => group.employees).map((employee) => [
            employee.name, employee.contract_type, employee.department, employee.shift, employee.status_label,
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
