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
        this.state = useState({ loading: true, data: null, error: "" });
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
            this.state.error = error.cause?.message || error.message || "Unable to load attendance.";
        } finally {
            this.state.loading = false;
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

    changeDate(ev) {
        this.load(ev.target.value);
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
