/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadCSS, loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";

const LEAFLET_VERSION = "1.9.4";
const LEAFLET_CSS = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css`;
const LEAFLET_JS = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js`;

function todayISO() {
    return new Date().toISOString().slice(0, 10);
}

function getMany2OneId(value) {
    if (!value) {
        return false;
    }
    return Array.isArray(value) ? value[0] : value.id;
}

function getMany2OneName(value) {
    if (!value) {
        return "";
    }
    return Array.isArray(value) ? value[1] : value.display_name;
}

function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function getCheckOutMarkerIcon() {
    return window.L.divIcon({
        className: "o_bambus_attendance_check_out_marker",
        html: `
            <svg viewBox="0 0 25 41" xmlns="http://www.w3.org/2000/svg" aria-label="Check Out">
                <path fill="#dc3545" stroke="#a71d2a" stroke-width="1.5"
                    d="M12.5 0C5.6 0 0 5.6 0 12.5c0 9.4 12.5 28.5 12.5 28.5S25 21.9 25 12.5C25 5.6 19.4 0 12.5 0Z"/>
                <circle cx="12.5" cy="12.5" r="4.5" fill="#fff"/>
            </svg>`,
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
    });
}

export class AttendanceLocationMapAction extends Component {
    static template = "bambus_hr_attendance_ot_fine.AttendanceLocationMapAction";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.mapRef = useRef("map");
        this.map = null;
        this.markers = [];
        this.markersByRecordId = new Map();
        this.employeeImageIds = new Set();

        this.state = useState({
            dateFrom: todayISO(),
            dateTo: todayISO(),
            employeeId: "",
            locationType: "",
            employees: [],
            records: [],
            loading: true,
            mapReady: false,
        });

        onWillStart(async () => {
            await Promise.all([this.loadLeaflet(), this.loadEmployees()]);
            await this.loadLocations();
        });

        onMounted(() => {
            this.initMap();
            this.renderMarkers();
        });

        onWillUnmount(() => {
            this.clearMarkers();
            if (this.map) {
                this.map.remove();
            }
        });
    }

    async loadLeaflet() {
        if (window.L) {
            return;
        }
        try {
            await loadCSS(LEAFLET_CSS);
            await loadJS(LEAFLET_JS);
        } catch {
            this.notification.add(
                "Could not load the map library. Please check internet access from the browser.",
                { type: "danger" }
            );
        }
    }

    async loadEmployees() {
        this.state.employees = await this.orm.searchRead(
            "hr.employee",
            [["active", "=", true]],
            ["name"],
            { order: "name" }
        );
    }

    getDomain() {
        const domain = [];
        if (this.state.employeeId) {
            domain.push(["employee_id", "=", Number(this.state.employeeId)]);
        }
        if (this.state.locationType) {
            domain.push(["location_type", "=", this.state.locationType]);
        }
        if (this.state.dateFrom) {
            domain.push(["attendance_datetime", ">=", `${this.state.dateFrom} 00:00:00`]);
        }
        if (this.state.dateTo) {
            domain.push(["attendance_datetime", "<=", `${this.state.dateTo} 23:59:59`]);
        }
        return domain;
    }

    async loadLocations() {
        this.state.loading = true;
        this.state.records = await this.orm.searchRead(
            "hr.attendance.location",
            this.getDomain(),
            [
                "employee_id",
                "location_type",
                "attendance_datetime",
                "check_in",
                "check_out",
                "latitude",
                "longitude",
                "attendance_id",
            ],
            { limit: 500, order: "attendance_datetime desc" }
        );
        const employeeIds = [
            ...new Set(this.state.records.map((record) => getMany2OneId(record.employee_id)).filter(Boolean)),
        ];
        const employees = employeeIds.length
            ? await this.orm.searchRead("hr.employee", [["id", "in", employeeIds]], ["image_128"])
            : [];
        this.employeeImageIds = new Set(
            employees.filter((employee) => employee.image_128).map((employee) => employee.id)
        );
        this.state.loading = false;
        this.renderMarkers();
    }

    initMap() {
        if (!window.L || this.map || !this.mapRef.el) {
            return;
        }
        this.map = window.L.map(this.mapRef.el, {
            scrollWheelZoom: true,
        });
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors",
        }).addTo(this.map);
        this.map.setView([20, 0], 2);
        this.state.mapReady = true;
        setTimeout(() => this.map.invalidateSize(), 0);
    }

    clearMarkers() {
        for (const marker of this.markers) {
            marker.remove();
        }
        this.markers = [];
        this.markersByRecordId.clear();
    }

    renderMarkers() {
        if (!this.map || !window.L) {
            return;
        }
        this.clearMarkers();
        const bounds = [];
        for (const record of this.state.records) {
            const latitude = Number(record.latitude);
            const longitude = Number(record.longitude);
            if (
                !Number.isFinite(latitude) ||
                !Number.isFinite(longitude) ||
                latitude < -90 || latitude > 90 ||
                longitude < -180 || longitude > 180
            ) {
                continue;
            }
            const employeeName = getMany2OneName(record.employee_id);
            const employeeId = getMany2OneId(record.employee_id);
            const type = record.location_type === "check_in" ? "Check In" : "Check Out";
            const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`;
            const employeeImageUrl = this.employeeImageIds.has(employeeId)
                ? `/web/image/hr.employee/${employeeId}/image_128`
                : "";
            const popup = `
                <div class="o_bambus_attendance_map_popup">
                    <div class="o_bambus_attendance_map_popup_details">
                        <strong>${escapeHtml(employeeName)}</strong><br/>
                        Employee ID: ${escapeHtml(employeeId)}<br/>
                        ${escapeHtml(type)}<br/>
                        ${escapeHtml(record.attendance_datetime)}<br/>
                        <a href="${mapsUrl}" target="_blank" rel="noopener noreferrer">Open in Google Maps</a>
                    </div>
                    ${employeeImageUrl ? `
                        <img class="o_bambus_attendance_map_popup_photo"
                            src="${employeeImageUrl}" alt=""/>
                    ` : ""}
                </div>
            `;
            const markerOptions = record.location_type === "check_out"
                ? { icon: getCheckOutMarkerIcon() }
                : {};
            const marker = window.L.marker([latitude, longitude], markerOptions).addTo(this.map);
            marker.bindPopup(popup);
            this.markers.push(marker);
            this.markersByRecordId.set(record.id, marker);
            bounds.push([latitude, longitude]);
        }
        if (bounds.length) {
            this.map.fitBounds(bounds, { padding: [24, 24], maxZoom: 16 });
        } else {
            this.map.setView([20, 0], 2);
        }
        setTimeout(() => this.map.invalidateSize(), 0);
    }

    async applyFilters() {
        await this.loadLocations();
    }

    async clearFilters() {
        this.state.dateFrom = todayISO();
        this.state.dateTo = todayISO();
        this.state.employeeId = "";
        this.state.locationType = "";
        await this.loadLocations();
    }

    openAttendance(record) {
        const attendanceId = getMany2OneId(record.attendance_id);
        if (!attendanceId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.attendance",
            res_id: attendanceId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    focusLocation(record) {
        const marker = this.markersByRecordId.get(record.id);
        if (!marker || !this.map) {
            return;
        }
        this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 16));
        marker.openPopup();
    }

    getEmployeeName(record) {
        return getMany2OneName(record.employee_id);
    }

    getEmployeeId(record) {
        return getMany2OneId(record.employee_id);
    }

    getLocationType(record) {
        return record.location_type === "check_in" ? "Check In" : "Check Out";
    }
}

registry.category("actions").add(
    "bambus_hr_attendance_locations_map",
    AttendanceLocationMapAction
);
