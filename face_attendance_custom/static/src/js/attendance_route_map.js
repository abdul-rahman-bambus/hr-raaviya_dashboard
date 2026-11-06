/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { loadCSS, loadJS } from "@web/core/assets";
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState, useEffect } from "@odoo/owl";
import { processRoutePoints } from "./route_geometry_utils";

const LEAFLET_LOCAL_CSS = "/face_attendance_custom/static/lib/leaflet/leaflet.css";
const LEAFLET_LOCAL_JS = "/face_attendance_custom/static/lib/leaflet/leaflet.js";
const LEAFLET_CDN_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_CDN_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";

export class AttendanceRouteMap extends Component {
    static template = "face_attendance_custom.AttendanceRouteMap";
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.mapRef = useRef("mapContainer");
        this.map = null;
        this.markers = [];
        this.routeGlowPolyline = null;
        this.routeCorePolyline = null;
        this.resizeObserver = null;

        this.state = useState({
            titleText: "Shift Attendance Route",
            googleMapsUrl: "",
            hasCoordinates: false,
        });

        onWillStart(async () => {
            await this.loadLeaflet();
        });

        onMounted(() => {
            if (!this.map && this.mapRef.el && window.L) {
                this.initMap();
            }
        });

        onWillUnmount(() => {
            this.cleanup();
        });

        useEffect(
            () => {
                if (!this.map && this.mapRef.el && window.L) {
                    this.initMap();
                }
                this.renderRoute();
            },
            () => [
                this.props.record?.data?.location_track_logs,
                this.props.record?.data?.tracking_route_url,
                this.props.record?.data?.in_latitude,
                this.props.record?.data?.out_latitude,
            ]
        );
    }

    async loadLeaflet() {
        if (!window.L) {
            try {
                await loadCSS(LEAFLET_LOCAL_CSS);
                await loadJS(LEAFLET_LOCAL_JS);
            } catch (_) {
                try {
                    await loadCSS(LEAFLET_CDN_CSS);
                    await loadJS(LEAFLET_CDN_JS);
                } catch (cdnErr) {
                    console.warn("Could not load Leaflet assets:", cdnErr);
                }
            }
        }
    }

    initMap() {
        if (!window.L || this.map || !this.mapRef.el) {
            return;
        }

        this.map = window.L.map(this.mapRef.el, {
            scrollWheelZoom: true,
            zoomControl: true,
        });

        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors",
        }).addTo(this.map);

        this.map.setView([20, 0], 2);

        // ResizeObserver to handle tab changes and modal resizing
        if (window.ResizeObserver && this.mapRef.el) {
            this.resizeObserver = new ResizeObserver(() => {
                if (this.map) {
                    this.map.invalidateSize();
                }
            });
            this.resizeObserver.observe(this.mapRef.el);
        }

        setTimeout(() => this.map && this.map.invalidateSize(), 50);
        setTimeout(() => this.map && this.map.invalidateSize(), 200);
        setTimeout(() => this.map && this.map.invalidateSize(), 600);
    }

    renderRoute() {
        if (!this.map || !window.L || !this.props.record?.data) {
            return;
        }

        this.clearLayers();

        const data = this.props.record.data;
        const coords = [];

        // 1. Try parsing JSON location track logs
        if (data.location_track_logs) {
            try {
                let parsed = data.location_track_logs;
                if (typeof parsed === "string") {
                    parsed = JSON.parse(parsed);
                }
                if (Array.isArray(parsed)) {
                    for (const item of parsed) {
                        const c = item.coordinates || item;
                        if (Array.isArray(c) && c.length >= 2) {
                            const lat = parseFloat(c[0]);
                            const lng = parseFloat(c[1]);
                            if (!isNaN(lat) && !isNaN(lng) && (lat !== 0 || lng !== 0)) {
                                coords.push({
                                    lat,
                                    lng,
                                    timestamp: item.timestamp || null,
                                });
                            }
                        }
                    }
                }
            } catch (e) {
                console.warn("Error parsing location_track_logs:", e);
            }
        }

        // 2. Fallback to checkin and checkout coordinates if logs are empty
        if (!coords.length) {
            const inLat = parseFloat(data.in_latitude);
            const inLng = parseFloat(data.in_longitude);
            if (!isNaN(inLat) && !isNaN(inLng) && (inLat !== 0 || inLng !== 0)) {
                coords.push({ lat: inLat, lng: inLng, label: "Check-in" });
            }

            const outLat = parseFloat(data.out_latitude);
            const outLng = parseFloat(data.out_longitude);
            if (!isNaN(outLat) && !isNaN(outLng) && (outLat !== 0 || outLng !== 0)) {
                coords.push({ lat: outLat, lng: outLng, label: "Check-out" });
            }
        }

        if (!coords.length) {
            this.state.titleText = "No attendance GPS coordinates recorded";
            this.state.googleMapsUrl = "";
            this.state.hasCoordinates = false;
            return;
        }

        this.state.hasCoordinates = true;
        this.state.titleText = "Shift Attendance Route";
        this.state.googleMapsUrl = data.tracking_route_url || "";

        const rawPoints = coords.map((c) => ({
            latitude: c.lat,
            longitude: c.lng,
            timestamp: c.timestamp,
        }));

        const processed = processRoutePoints(rawPoints);
        const renderCoords = processed.smoothedCoords && processed.smoothedCoords.length > 1
            ? processed.smoothedCoords
            : processed.rawCoords;

        // Draw dual-layer route polyline
        if (renderCoords.length > 1) {
            this.routeGlowPolyline = window.L.polyline(renderCoords, {
                color: "#3b82f6",
                weight: 7,
                opacity: 0.28,
                lineCap: "round",
                lineJoin: "round",
            }).addTo(this.map);

            this.routeCorePolyline = window.L.polyline(renderCoords, {
                color: "#2563eb",
                weight: 3.5,
                opacity: 0.95,
                lineCap: "round",
                lineJoin: "round",
            }).addTo(this.map);
        }

        const rawLatLngs = processed.rawCoords;

        // Check-in Start Marker (Green)
        const startIcon = window.L.divIcon({
            className: "o_start_pin_wrapper",
            html: `<div class="o_start_pin_icon" title="Check-in"><i class="fa fa-sign-in"></i></div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });
        const startMarker = window.L.marker(rawLatLngs[0], { icon: startIcon })
            .bindPopup(`<b>Check-in Location</b><br/>${data.checkin_address || ""}`)
            .addTo(this.map);
        this.markers.push(startMarker);

        // Check-out End Marker (Red) if available
        if (rawLatLngs.length > 1 && data.check_out) {
            const endIcon = window.L.divIcon({
                className: "o_end_pin_wrapper",
                html: `<div class="o_end_pin_icon" title="Check-out"><i class="fa fa-sign-out"></i></div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            });
            const endMarker = window.L.marker(rawLatLngs[rawLatLngs.length - 1], { icon: endIcon })
                .bindPopup(`<b>Check-out Location</b><br/>${data.checkout_address || ""}`)
                .addTo(this.map);
            this.markers.push(endMarker);
        }

        // Fit map bounds
        const fitCoords = renderCoords.length > 1 ? renderCoords : rawLatLngs;
        if (fitCoords.length > 1) {
            const bounds = window.L.latLngBounds(fitCoords);
            this.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 17 });
        } else if (this.markers.length) {
            this.map.setView(this.markers[0].getLatLng(), 16);
        }

        setTimeout(() => this.map && this.map.invalidateSize(), 100);
    }

    clearLayers() {
        for (const m of this.markers) {
            m.remove();
        }
        this.markers = [];
        if (this.routeGlowPolyline) {
            this.routeGlowPolyline.remove();
            this.routeGlowPolyline = null;
        }
        if (this.routeCorePolyline) {
            this.routeCorePolyline.remove();
            this.routeCorePolyline = null;
        }
    }

    fitBounds() {
        if (!this.map) {
            return;
        }
        if (this.routeCorePolyline) {
            this.map.fitBounds(this.routeCorePolyline.getBounds(), { padding: [30, 30] });
        } else if (this.markers.length > 1) {
            const group = window.L.featureGroup(this.markers);
            this.map.fitBounds(group.getBounds(), { padding: [30, 30] });
        }
        setTimeout(() => this.map && this.map.invalidateSize(), 50);
    }

    cleanup() {
        this.clearLayers();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        if (this.map) {
            this.map.remove();
            this.map = null;
        }
    }
}

export const attendanceRouteMapWidget = {
    component: AttendanceRouteMap,
};

registry.category("view_widgets").add("attendance_route_map", attendanceRouteMapWidget);
