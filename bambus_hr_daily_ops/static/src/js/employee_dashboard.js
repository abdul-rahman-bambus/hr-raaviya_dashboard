/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class EmployeeDashboard extends Component {
    static template = "bambus_hr_daily_ops.EmployeeDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            employees: [],
            loading: true,
            error: "",
            query: "",
            departmentId: "all",
            showFilters: false,
            selectedIds: [],
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.employees = await this.orm.searchRead(
                "hr.employee",
                [["active", "=", true]],
                ["name", "barcode", "job_id", "department_id", "work_email", "mobile_phone"],
                { order: "name asc" }
            );
        } catch (error) {
            this.state.error = error.cause?.message || error.message || "Unable to load employees.";
        } finally {
            this.state.loading = false;
        }
    }

    get departments() {
        const values = new Map();
        for (const employee of this.state.employees) {
            if (employee.department_id) {
                values.set(employee.department_id[0], employee.department_id[1]);
            }
        }
        return [...values.entries()].map(([id, name]) => ({ id, name }))
            .sort((left, right) => left.name.localeCompare(right.name));
    }

    get filteredEmployees() {
        const query = this.state.query.trim().toLowerCase();
        return this.state.employees.filter((employee) => {
            const matchesDepartment = this.state.departmentId === "all" ||
                employee.department_id?.[0] === Number(this.state.departmentId);
            const matchesQuery = !query || [
                employee.name,
                employee.barcode,
                employee.job_id?.[1],
                employee.department_id?.[1],
                employee.work_email,
                employee.mobile_phone,
            ].some((value) => (value || "").toLowerCase().includes(query));
            return matchesDepartment && matchesQuery;
        });
    }

    get employeeGroups() {
        const groups = new Map();
        for (const employee of this.filteredEmployees) {
            const id = employee.department_id?.[0] || 0;
            const name = employee.department_id?.[1] || "No Department";
            if (!groups.has(id)) {
                groups.set(id, { id, name, employees: [] });
            }
            groups.get(id).employees.push(employee);
        }
        return [...groups.values()].sort((left, right) => left.name.localeCompare(right.name));
    }

    get allSelected() {
        return Boolean(this.filteredEmployees.length) &&
            this.filteredEmployees.every((employee) => this.state.selectedIds.includes(employee.id));
    }

    avatarUrl(employeeId) {
        return `/web/image/hr.employee/${employeeId}/avatar_128`;
    }

    updateQuery(event) {
        this.state.query = event.target.value;
    }

    updateDepartment(event) {
        this.state.departmentId = event.target.value;
    }

    toggleEmployee(employeeId) {
        const index = this.state.selectedIds.indexOf(employeeId);
        if (index === -1) {
            this.state.selectedIds.push(employeeId);
        } else {
            this.state.selectedIds.splice(index, 1);
        }
    }

    toggleAll() {
        const visibleIds = this.filteredEmployees.map((employee) => employee.id);
        if (this.allSelected) {
            this.state.selectedIds = this.state.selectedIds.filter((id) => !visibleIds.includes(id));
        } else {
            this.state.selectedIds = [...new Set([...this.state.selectedIds, ...visibleIds])];
        }
    }

    openEmployee(employeeId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            res_id: employeeId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    addEmployee() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openStandardList() {
        this.action.doAction("bambus_hr_daily_ops.action_bambus_employee_list");
    }
}

registry.category("actions").add("bambus_employee_dashboard", EmployeeDashboard);
