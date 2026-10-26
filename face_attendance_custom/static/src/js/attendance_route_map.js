/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { loadCSS, loadJS } from "@web/core/assets";
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState, useEffect } from "@odoo/owl";

const LEAFLET_LOCAL_CSS = "/face_attendance_custom/static/lib/leaflet/leaflet.css";
const LEAFLET_LOCAL_JS = "/face_attendance_custom/static/lib/leaflet/leaflet.js";
const ROUTING_LOCAL_CSS = "/face_attendance_custom/static/lib/leaflet-routing-machine/leaflet-routing-machine.css";
const ROUTING_LOCAL_JS = "/face_attendance_custom/static/lib/leaflet-routing-machine/leaflet-routing-machine.min.js";
const LEAFLET_CDN_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_CDN_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const ROUTING_CDN_CSS = "https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css";
const ROUTING_CDN_JS = "https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.min.js";

export class AttendanceRouteMap extends Component {
    static template = "face_attendance_custom.AttendanceRouteMap";
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.mapRef = useRef("mapContainer");
        this.map = null;
        this.markers = [];
        this.routePolyline = null;
        this.routingControl = null;
        this.resizeObserver = null;

        this.state = useState({
            titleText: "Shift Attendance Route",
            pointCountText: "",
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
        if (window.L && !window.L.Routing) {
            try {
                await loadCSS(ROUTING_LOCAL_CSS);
                await loadJS(ROUTING_LOCAL_JS);
            } catch (_) {
                try {
                    await loadCSS(ROUTING_CDN_CSS);
                    await loadJS(ROUTING_CDN_JS);
                } catch (rErr) {
                    console.warn("Could not load Leaflet Routing Machine assets:", rErr);
                }
            }
        }
        if (window.L && window.L.Routing && window.L.Routing.Control) {
            if (!window.L.Routing.Control.prototype._safePatched) {
                window.L.Routing.Control.prototype._safePatched = true;
                const origClearLines = window.L.Routing.Control.prototype._clearLines;
                window.L.Routing.Control.prototype._clearLines = function () {
                    if (!this._map) {
                        delete this._line;
                        this._alternatives = [];
                        return;
                    }
                    return origClearLines.apply(this, arguments);
                };
                const origOnRemove = window.L.Routing.Control.prototype.onRemove;
                window.L.Routing.Control.prototype.onRemove = function (map) {
                    if (this._pendingRequest && this._pendingRequest.abort) {
                        try {
                            this._pendingRequest.abort();
                        } catch (_) {}
                        this._pendingRequest = null;
                    }
                    return origOnRemove.apply(this, arguments);
                };
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
            this.state.pointCountText = "";
            this.state.googleMapsUrl = "";
            this.state.hasCoordinates = false;
            return;
        }

        this.state.hasCoordinates = true;
        this.state.pointCountText = `(${coords.length} GPS waypoint${coords.length > 1 ? "s" : ""})`;
        this.state.titleText = "Shift Attendance Route";
        this.state.googleMapsUrl = data.tracking_route_url || "";

        const latLngs = coords.map((c) => [c.lat, c.lng]);

        // Draw initial polyline immediately
        if (latLngs.length > 1) {
            this.routePolyline = window.L.polyline(latLngs, {
                color: "#007bff",
                weight: 4,
                opacity: 0.85,
                lineJoin: "round",
            }).addTo(this.map);

            // Enhance with Leaflet Routing Machine road-snapped line
            if (window.L.Routing) {
                try {
                    let sampledLatLngs = latLngs;
                    if (latLngs.length > 20) {
                        sampledLatLngs = [latLngs[0]];
                        const step = (latLngs.length - 2) / 18;
                        for (let i = 0; i < 18; i++) {
                            sampledLatLngs.push(latLngs[Math.round(1 + i * step)]);
                        }
                        sampledLatLngs.push(latLngs[latLngs.length - 1]);
                    }

                    const waypoints = sampledLatLngs.map((pt) => window.L.latLng(pt[0], pt[1]));

                    this.routingControl = window.L.Routing.control({
                        waypoints: waypoints,
                        router: window.L.Routing.osrmv1({
                            serviceUrl: "https://router.project-osrm.org/route/v1",
                            profile: "driving",
                        }),
                        lineOptions: {
                            styles: [{ color: "#007bff", weight: 5, opacity: 0.85 }],
                            extendToWaypoints: true,
                            missingRouteStyles: [{ color: "#007bff", weight: 4, opacity: 0.5, dashArray: "5, 10" }],
                        },
                        addWaypoints: false,
                        draggableWaypoints: false,
                        fitSelectedRoutes: false,
                        showAlternatives: false,
                        show: false,
                        createMarker: () => null,
                    }).addTo(this.map);

                    this.routingControl.on("routesfound", () => {
                        if (!this.map) return;
                        if (this.routePolyline) {
                            this.routePolyline.remove();
                            this.routePolyline = null;
                        }
                    });
                    this.routingControl.on("routingerror", (e) => {
                        console.warn("Leaflet Routing Machine route calculation warning:", e?.error || e);
                    });
                } catch (routingErr) {
                    console.warn("Leaflet Routing Machine initialization skipped, fallback polyline active:", routingErr);
                }
            }
        }

        // Check-in Start Marker (Green)
        const startIcon = window.L.divIcon({
            className: "o_start_pin_wrapper",
            html: `<div class="o_start_pin_icon" title="Check-in"><i class="fa fa-sign-in"></i></div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });
        const startMarker = window.L.marker(latLngs[0], { icon: startIcon })
            .bindPopup(`<b>Check-in Location</b><br/>${data.checkin_address || ""}`)
            .addTo(this.map);
        this.markers.push(startMarker);

        // Check-out End Marker (Red) if available
        if (latLngs.length > 1 && data.check_out) {
            const endIcon = window.L.divIcon({
                className: "o_end_pin_wrapper",
                html: `<div class="o_end_pin_icon" title="Check-out"><i class="fa fa-sign-out"></i></div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            });
            const endMarker = window.L.marker(latLngs[latLngs.length - 1], { icon: endIcon })
                .bindPopup(`<b>Check-out Location</b><br/>${data.checkout_address || ""}`)
                .addTo(this.map);
            this.markers.push(endMarker);
        }

        // Fit map bounds
        if (latLngs.length > 1) {
            const bounds = window.L.latLngBounds(latLngs);
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
        if (this.routingControl) {
            try {
                if (this.routingControl._pendingRequest && this.routingControl._pendingRequest.abort) {
                    this.routingControl._pendingRequest.abort();
                    this.routingControl._pendingRequest = null;
                }
                if (this.map) {
                    this.map.removeControl(this.routingControl);
                }
            } catch (_) {}
            this.routingControl = null;
        }
        if (this.routePolyline) {
            this.routePolyline.remove();
            this.routePolyline = null;
        }
    }

    fitBounds() {
        if (!this.map) {
            return;
        }
        if (this.routePolyline) {
            this.map.fitBounds(this.routePolyline.getBounds(), { padding: [30, 30] });
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
