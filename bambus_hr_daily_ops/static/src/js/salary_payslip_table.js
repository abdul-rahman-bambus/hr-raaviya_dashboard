/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatDate } from "@web/core/l10n/dates";
import { formatMonetary } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Pager } from "@web/core/pager/pager";

export class SalaryPayslipTable extends Component {
    static template = "bambus_hr_daily_ops.SalaryPayslipTable";
    static props = { ...standardFieldProps };
    static components = { Pager };

    setup() {
        this.action = useService("action");
    }

    get list() {
        return this.props.record.data[this.props.name];
    }

    get rows() {
        return this.list.records;
    }

    get totals() {
        return this.rows.reduce((total, row) => {
            for (const name of ["basic_pay", "gross_pay", "net_pay"]) {
                total[name] += row.data[name] || 0;
            }
            return total;
        }, { basic_pay: 0, gross_pay: 0, net_pay: 0 });
    }

    get pagerProps() {
        return {
            offset: this.list.offset,
            limit: this.list.limit,
            total: this.list.count,
            withAccessKey: false,
            onUpdate: async ({ offset, limit }) => {
                await this.list.load({ offset, limit });
                this.render();
            },
        };
    }

    date(value) {
        return value ? formatDate(value) : "";
    }

    money(value) {
        const currency = this.props.record.data.payslip_currency_id;
        return formatMonetary(value || 0, { currencyId: Array.isArray(currency) ? currency[0] : currency });
    }

    status(row) {
        return (row.fields.state.selection || []).find(([key]) => key === row.data.state)?.[1] || row.data.state;
    }

    openPayslip(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.payslip",
            res_id: row.resId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("fields").add("bambus_salary_payslips", {
    component: SalaryPayslipTable,
    supportedTypes: ["one2many"],
    isEmpty: () => false,
    relatedFields: [
        { name: "name", type: "char" },
        { name: "date_from", type: "date" },
        { name: "date_to", type: "date" },
        { name: "basic_pay", type: "float" },
        { name: "gross_pay", type: "float" },
        { name: "net_pay", type: "float" },
        { name: "state", type: "selection", selection: [
            ["draft", _t("Draft")], ["verify", _t("Waiting")],
            ["done", _t("Done")], ["cancel", _t("Rejected")],
        ] },
    ],
});
