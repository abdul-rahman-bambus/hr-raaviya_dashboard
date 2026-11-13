/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AttendanceDashboard extends Component {
    static template = "bambus_hr_daily_ops.AttendanceDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const actionParams = this.props.action?.params || {};
        this.initialDate = actionParams.selected_date;
        this.state = useState({
            loading: true,
            data: null,
            selectedDate: this.initialDate || this.today(),
            error: "",
            query: actionParams.employee_query || "",
            employeeFilterId: actionParams.filter_employee_id || false,
            statusFilter: actionParams.metric_filter || "all",
            currentPage: 1,
            pageSize: 10,
            collapsedContractTypes: {},
            savingIds: {},
            serverPaging: false, hasMore: false, nextOffset: 0, totalRows: 0,
            loadingMore: false, moreError: "",
        });
        this.loadSequence = 0;
        this.batchSize = 25;
        this.scrollSentinel = useRef("scrollSentinel");
        useEffect(() => {
            if (!this.state.serverPaging || !this.state.hasMore || this.state.loading ||
                this.state.loadingMore || this.state.moreError || this.dateNavigationLocked || !this.scrollSentinel.el) return;
            const observer = new IntersectionObserver(entries => {
                if (entries.some(entry => entry.isIntersecting)) this.loadMore();
            }, {root: this.scrollSentinel.el.closest('.o_bambus_attendance_dashboard'), rootMargin: '160px'});
            observer.observe(this.scrollSentinel.el);
            return () => observer.disconnect();
        }, () => [this.state.data?.date, this.state.serverPaging, this.state.hasMore,
            this.state.loading, this.state.loadingMore, this.state.moreError, this.dateNavigationLocked]);
        onWillUnmount(() => { clearTimeout(this.filterTimer); ++this.loadSequence; });
        onWillStart(() => this.load(this.initialDate));
    }

    async load(date) {
        const selectedDate = date || this.state.selectedDate;
        if (!selectedDate) return;
        const dateChanged = selectedDate !== this.state.data?.date;
        // Keep edits tied to their original day until autosave/dialogs finish.
        if (dateChanged && this.dateNavigationLocked) return;
        clearTimeout(this.filterTimer);
        const sequence = ++this.loadSequence;
        this.state.loadingMore = false;
        this.state.moreError = "";
        this.state.selectedDate = selectedDate;
        this.state.loading = true;
        this.state.error = "";
        try {
            // We render our own inline loading/error states. Avoid Odoo's
            // global RPC loading overlay while changing or refreshing a day.
            const data = await this.orm.silent.call(
                "bambus.attendance.dashboard",
                "get_attendance_dashboard",
                [],
                {selected_date: selectedDate, offset: 0, limit: this.batchSize, ...this.serverFilters}
            );
            // A slower response for the previous date must never overwrite the
            // most recently selected date.
            if (sequence === this.loadSequence) {
                if (dateChanged) this.state.logEmployee = null;
                this.state.data = { ...data };
                this.applyPaging(data);
                this.state.currentPage = dateChanged ? 1 : Math.min(
                    this.state.currentPage,
                    this.refreshPageCount
                );
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

    get serverFilters() {
        return {query: this.state.query, status_filter: this.state.statusFilter,
            employee_filter_id: this.state.employeeFilterId || false};
    }

    applyPaging(data) {
        this.state.serverPaging = Boolean(data.paging);
        this.state.hasMore = Boolean(data.paging?.has_more);
        this.state.nextOffset = data.paging?.next_offset || 0;
        this.state.totalRows = data.paging?.total ?? data.daily_attendance.length;
    }

    async loadMore() {
        if (!this.state.serverPaging || !this.state.hasMore || this.state.loading || this.state.loadingMore ||
                this.dateNavigationLocked || this.state.selectedDate !== this.state.data?.date) return;
        const sequence = this.loadSequence;
        const date = this.state.data.date;
        this.state.loadingMore = true;
        this.state.moreError = "";
        try {
            const data = await this.orm.silent.call("bambus.attendance.dashboard", "get_attendance_dashboard", [], {
                selected_date: date, offset: this.state.nextOffset, limit: this.batchSize, ...this.serverFilters,
            });
            if (sequence !== this.loadSequence || date !== this.state.selectedDate) return;
            const existing = new Set(this.state.data.daily_attendance.map(employee => employee.id));
            this.state.data.daily_attendance.push(...data.daily_attendance.filter(employee => !existing.has(employee.id)));
            this.state.data.metrics = data.metrics;
            this.state.data.departments = data.departments;
            this.state.data.shifts = data.shifts;
            this.applyPaging(data);
        } catch (error) {
            if (sequence === this.loadSequence) this.state.moreError = error.cause?.message || error.message || "Unable to load more employees.";
        } finally {
            if (sequence === this.loadSequence) this.state.loadingMore = false;
        }
    }

    queueFilteredLoad() {
        if (!this.state.serverPaging) return;
        clearTimeout(this.filterTimer);
        ++this.loadSequence; // Invalidate an older batch immediately on a filter change.
        this.state.loading = true;
        this.state.loadingMore = false;
        const retry = () => {
            if (this.dateNavigationLocked) this.filterTimer = setTimeout(retry, 150);
            else this.load();
        };
        this.filterTimer = setTimeout(retry, 200);
    }

    get refreshPageCount() {
        return this.dashboardPageCount;
    }

    get dateNavigationLocked() {
        return Object.values(this.state.savingIds).some(Boolean) ||
            Boolean(this.state.adjustment || this.state.timingAdjustment || this.state.paidDayDecision);
    }

    get canEditAttendance() {
        return !this.state.loading && this.state.selectedDate === this.state.data?.date;
    }

    today() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
    }

    formatHours(value) {
        // Native Odoo overtime can be negative when worked hours are below a
        // schedule. A shortfall is not overtime and must never be displayed as
        // a negative HH:MM value on the OT/Fine review dashboard.
        const minutes = Math.round(Math.max(Number(value) || 0, 0) * 60);
        return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
    }

    metricValue(metric) {
        const value = this.state.data.metrics[metric[0]];
        return metric[3] === "hours" ? this.formatHours(value) : value;
    }

    get filteredDailyEmployees() {
        const query = this.state.query.trim().toLowerCase();
        return (this.state.data?.daily_attendance || []).filter((employee) => {
            if (this.state.employeeFilterId && employee.id !== this.state.employeeFilterId) return false;
            const matchesStatus = this.state.statusFilter === "all" ||
                (this.state.statusFilter === "overtime" && (employee.overtime_hours > 0 || employee.overtime_review_pending)) ||
                (this.state.statusFilter === "fine" && (employee.fine_hours > 0 || employee.fine_review_pending)) ||
                (this.state.statusFilter === "overtime_review" && employee.overtime_review_pending) ||
                (this.state.statusFilter === "fine_review" && employee.fine_review_pending) ||
                employee.status === this.state.statusFilter;
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
        if (this.state.serverPaging) return [this.filteredDailyGroups];
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
        if (this.state.serverPaging) return this.filteredDailyEmployees;
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
        this.queueFilteredLoad();
    }

    updateStatusFilter(ev) {
        this.state.statusFilter = ev.target.value;
        this.state.currentPage = 1;
        this.queueFilteredLoad();
    }

    openMetric(metric) {
        if (!["overtime", "fine"].includes(metric)) {
            return;
        }
        // Filter the already-loaded dashboard in place. Launching another
        // client action here loses the current action metadata in Odoo 18 and
        // can fail while the action service tries to map undefined views.
        this.state.statusFilter = metric;
        this.state.currentPage = 1;
        this.queueFilteredLoad();
    }

    openReviewMetric(metric) {
        this.state.statusFilter = `${metric}_review`;
        this.state.currentPage = 1;
        this.queueFilteredLoad();
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
        return hours > 0 ? this.formatHours(hours) : "—";
    }

    updateEmployeeField(employee, field, event) {
        employee[field] = event.target.value;
    }

    async setStatus(employee, status) {
        if (!this.canEditAttendance || this.state.savingIds[employee.id]) return;
        employee.status = status;
        employee.status_label = {
            present: "Present", absent: "Absent", halfday: "Half Day", leave: "Leave",
        }[status];
        await this.saveEmployee(employee);
    }

    async saveEmployee(employee) {
        if (!this.canEditAttendance || this.state.savingIds[employee.id]) {
            return;
        }
        this.state.savingIds[employee.id] = true;
        try {
            await this.orm.call(
                "bambus.attendance.dashboard",
                "update_dashboard_attendance",
                [employee.id, this.state.data.date, {
                    status: ["not_marked", "paid_weekly_off", "paid_public_holiday", "unpaid_weekly_off", "unpaid_public_holiday"].includes(employee.status) ? "absent" : employee.status,
                    check_in: employee.check_in_value || false,
                    check_out: employee.check_out_value || false,
                    overtime_hours: Number(employee.overtime_hours) || 0,
                    fine_hours: Number(employee.fine_hours) || 0,
                }]
            );
            this.notification.add(`${employee.name} attendance updated.`, { type: "success" });
            if (this.state.serverPaging) {
                const data = await this.orm.silent.call('bambus.attendance.dashboard', 'get_attendance_dashboard', [], {
                    selected_date: this.state.data.date, offset:0, limit:1, employee_filter_id:employee.id,
                });
                const updated = data.daily_attendance.find(row => row.id === employee.id);
                if (updated) Object.assign(employee, updated);
                this.state.data.metrics = data.metrics;
                this.state.data.departments = data.departments;
                this.state.data.shifts = data.shifts;
                if (this.state.statusFilter !== 'all') await this.load(this.state.data.date);
            } else await this.load(this.state.data.date);
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

    async downloadDailyAttendance() {
        const date = this.state.data.date;
        let employees = this.filteredDailyEmployees;
        if (this.state.serverPaging) {
            try {
                const data = await this.orm.silent.call('bambus.attendance.dashboard', 'get_attendance_dashboard', [], {
                    selected_date: date, include_logs: false, ...this.serverFilters,
                });
                employees = data.daily_attendance;
            } catch (error) {
                this.notification.add(error.cause?.message || error.message || 'Unable to download attendance.', {type:'danger'});
                return;
            }
        }
        const headers = ["Name", "Contract Type", "Department", "Work Schedule", "Attendance", "In Time", "Out Time", "Fine Hours"];
        const rows = employees.map((employee) => [
            employee.name, employee.contract_type, employee.department, employee.shift, employee.status_label,
            employee.check_in, employee.check_out, this.fineDisplay(employee.fine_hours),
        ]);
        const csv = [headers, ...rows].map((row) => row.map((value) =>
            `"${String(value ?? "").replaceAll('"', '""')}"`
        ).join(",")).join("\n");
        const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `daily-attendance-${date}.csv`;
        link.click();
        URL.revokeObjectURL(url);
    }

    async changeDate(ev) {
        await this.load(ev.target.value);
        ev.target.value = this.state.selectedDate;
    }

    moveDate(offset) {
        const date = new Date(`${this.state.selectedDate}T00:00:00Z`);
        date.setUTCDate(date.getUTCDate() + offset);
        this.load(date.toISOString().slice(0, 10));
    }


}

registry.category("actions").add("bambus_attendance_dashboard", AttendanceDashboard);
