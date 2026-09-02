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
        this.company = useService("company");
        this.state = useState({ loading: true, query: "", data: null, error: "" });
        onWillStart(() => this.load());
    }

    async load(date) {
        this.state.loading = true;
        this.state.error = "";
        const selectedDate = date || this.state.data?.date || this.today();
        try {
            this.state.data = await this.orm.call(
                "bambus.hr.attendance.sheet",
                "get_attendance_dashboard",
                [],
                { selected_date: selectedDate }
            );
        } catch (error) {
            if (!this.isMissingDashboardMethod(error)) {
                this.state.error = error.cause?.message || error.message || "Unable to load attendance.";
                this.state.loading = false;
                return;
            }
            // Asset bundles can be refreshed before the Odoo workers are restarted.
            // Keep the dashboard operational during that deployment window.
            try {
                this.state.data = await this.loadFromStandardOrm(selectedDate);
            } catch (fallbackError) {
                this.state.error = fallbackError.cause?.message || fallbackError.message || "Unable to load attendance.";
            }
        } finally {
            this.state.loading = false;
        }
    }

    today() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
    }

    isMissingDashboardMethod(error) {
        const details = [
            error?.message,
            error?.cause?.message,
            error?.cause?.data?.message,
            error?.cause?.data?.debug,
            error?.data?.message,
            error?.data?.debug,
        ].filter(Boolean).join(" ");
        return details.includes("get_attendance_dashboard") && details.includes("does not exist");
    }

    async loadFromStandardOrm(date) {
        const companyId = this.company.currentCompany.id;
        const sheets = await this.orm.searchRead(
            "bambus.hr.attendance.sheet",
            [["date", "=", date], ["company_id", "=", companyId]],
            ["state", "company_id"],
            { limit: 1 }
        );
        const data = this.emptySnapshot(date, this.company.currentCompany.name);
        if (!sheets.length) return data;
        const sheet = sheets[0];
        data.sheet_id = sheet.id;
        data.state = sheet.state;
        data.state_label = { draft: "Draft", submitted: "Submitted", approved: "Approved" }[sheet.state] || sheet.state;
        const lines = await this.orm.searchRead(
            "bambus.hr.attendance.sheet.line",
            [["sheet_id", "=", sheet.id]],
            ["employee_id", "department_id", "contract_id", "status", "check_in", "check_out",
                "worked_hours", "overtime_hours", "fine_hours", "fine_amount"]
        );
        const contractIds = [...new Set(lines.map((line) => line.contract_id?.[0]).filter(Boolean))];
        const calendarsByContract = {};
        if (contractIds.length) {
            const contracts = await this.orm.searchRead(
                "hr.contract", [["id", "in", contractIds]], ["resource_calendar_id"]
            );
            for (const contract of contracts) {
                calendarsByContract[contract.id] = contract.resource_calendar_id?.[1] || "No Shift";
            }
        }
        const statusLabels = { present: "Present", absent: "Absent", leave: "Leave", halfday: "Half Day" };
        const departments = {};
        const shifts = {};
        for (const line of lines) {
            const department = line.department_id?.[1] || "No Department";
            const shift = calendarsByContract[line.contract_id?.[0]] || "No Shift";
            this.addToGroup(departments, department, line);
            this.addToGroup(shifts, shift, line);
            data.employees.push({
                id: line.id,
                name: line.employee_id?.[1] || "",
                department,
                shift,
                status: line.status,
                status_label: statusLabels[line.status] || line.status,
                check_in: this.formatDateTime(line.check_in),
                check_out: this.formatDateTime(line.check_out),
                worked_hours: this.formatHours(line.worked_hours),
                overtime: this.formatHours(line.overtime_hours),
                fine: this.formatHours(line.fine_hours),
                fine_amount: line.fine_amount || 0,
            });
        }
        data.employees.sort((a, b) => a.name.localeCompare(b.name));
        data.departments = Object.values(departments);
        data.shifts = Object.values(shifts);
        this.calculateMetrics(data.metrics, lines);
        return data;
    }

    emptySnapshot(date, company) {
        return {
            date, company, sheet_id: false, state: false, state_label: "",
            metrics: { total: 0, present: 0, absent: 0, halfday: 0, leave: 0,
                punched_in: 0, punched_out: 0, not_marked: 0, overtime: 0, fine: 0,
                fine_amount: 0 },
            departments: [], shifts: [], employees: [],
        };
    }

    addToGroup(groups, name, line) {
        const group = groups[name] ||= { name, total: 0, present: 0, absent: 0, halfday: 0, leave: 0, not_marked: 0 };
        group.total++;
        group[line.status]++;
        if (!line.check_in && line.status === "absent") group.not_marked++;
    }

    calculateMetrics(metrics, lines) {
        metrics.total = lines.length;
        for (const line of lines) {
            metrics[line.status]++;
            if (line.check_in) metrics.punched_in++;
            if (line.check_out) metrics.punched_out++;
            if (!line.check_in && line.status === "absent") metrics.not_marked++;
            metrics.overtime += line.overtime_hours || 0;
            metrics.fine += line.fine_hours || 0;
            metrics.fine_amount += line.fine_amount || 0;
        }
        for (const key of ["overtime", "fine", "fine_amount"]) metrics[key] = Math.round(metrics[key] * 100) / 100;
    }

    formatHours(value) {
        const minutes = Math.round((value || 0) * 60);
        return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
    }

    formatDateTime(value) {
        if (!value) return "—";
        const date = new Date(value.replace(" ", "T") + "Z");
        return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }

    changeDate(ev) {
        this.load(ev.target.value);
    }

    moveDate(offset) {
        const date = new Date(`${this.state.data.date}T00:00:00Z`);
        date.setUTCDate(date.getUTCDate() + offset);
        this.load(date.toISOString().slice(0, 10));
    }

    get employees() {
        const query = this.state.query.trim().toLowerCase();
        if (!query) return this.state.data?.employees || [];
        return this.state.data.employees.filter((employee) =>
            [employee.name, employee.department, employee.shift, employee.status_label]
                .some((value) => value.toLowerCase().includes(query))
        );
    }

    openSheet() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Attendance Sheet",
            res_model: "bambus.hr.attendance.sheet",
            res_id: this.state.data.sheet_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    createSheet() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Attendance Sheet",
            res_model: "bambus.hr.attendance.sheet",
            views: [[false, "form"]],
            target: "current",
            context: { default_date: this.state.data.date },
        });
    }

    openHistory() {
        this.action.doAction("bambus_hr_daily_ops.action_bambus_hr_attendance_sheet");
    }
}

registry.category("actions").add("bambus_attendance_dashboard", AttendanceDashboard);
