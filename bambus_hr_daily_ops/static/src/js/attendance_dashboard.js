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
        this.state = useState({ loading: true, query: "", data: null });
        onWillStart(() => this.load());
    }

    async load(date) {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "bambus.hr.attendance.sheet",
            "get_attendance_dashboard",
            [],
            { selected_date: date || this.state.data?.date || false }
        );
        this.state.loading = false;
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
