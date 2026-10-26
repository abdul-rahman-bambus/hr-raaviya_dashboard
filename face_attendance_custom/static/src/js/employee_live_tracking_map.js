/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useService } from "@web/core/utils/hooks";
import { loadCSS, loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState, useEffect } from "@odoo/owl";

const LEAFLET_LOCAL_CSS = "/face_attendance_custom/static/lib/leaflet/leaflet.css";
const LEAFLET_LOCAL_JS = "/face_attendance_custom/static/lib/leaflet/leaflet.js";
const ROUTING_LOCAL_CSS = "/face_attendance_custom/static/lib/leaflet-routing-machine/leaflet-routing-machine.css";
const ROUTING_LOCAL_JS = "/face_attendance_custom/static/lib/leaflet-routing-machine/leaflet-routing-machine.min.js";
const LEAFLET_CDN_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_CDN_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const ROUTING_CDN_CSS = "https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css";
const ROUTING_CDN_JS = "https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.min.js";

export class EmployeeLiveTrackingMap extends Component {
    static template = "face_attendance_custom.EmployeeLiveTrackingMap";
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        this.orm = useService("orm");
        try {
            this.busService = useService("bus_service");
        } catch (_) {
            this.busService = null;
        }
        this.mapRef = useRef("mapContainer");

        this.map = null;
        this.startMarker = null;
        this.currentMarker = null;
        this.routePolyline = null;
        this.routingControl = null;
        this.pollInterval = null;
        this.resizeObserver = null;
        this.lastTimestamp = null;
        this.locationData = null;

        this.state = useState({
            loading: true,
            isLive: false,
            hasPoints: false,
            pointCount: 0,
            lastUpdatedText: "",
            statusText: "Initializing Live Tracking...",
            googleMapsUrl: "",
            latitude: null,
            longitude: null,
        });

        onWillStart(async () => {
            await this.loadLeaflet();
            await this.loadLocationData();
        });

        onMounted(() => {
            if (!this.map && this.mapRef.el && window.L) {
                this.initMap();
                this.renderRoute();
            }
            this.setupLiveListeners();
        });

        onWillUnmount(() => {
            this.cleanup();
        });

        useEffect(
            () => {
                if (!this.map && this.mapRef.el && window.L) {
                    this.initMap();
                }
                if (this.props.record?.resId) {
                    this.loadLocationData().then(() => {
                        this.renderRoute();
                    });
                }
            },
            () => [this.props.record?.resId, this.props.record?.data?.track_employee]
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
                    console.warn("Could not load Leaflet map assets:", cdnErr);
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

    get employeeId() {
        return this.props.record?.resId || false;
    }

    get employeeName() {
        return this.props.record?.data?.name || "Employee";
    }

    async loadLocationData() {
        // Read initial coordinates from current form record if present
        const recData = this.props.record?.data;
        if (recData) {
            const rLat = parseFloat(recData.track_latitude);
            const rLng = parseFloat(recData.track_longitude);
            if (!isNaN(rLat) && !isNaN(rLng) && (rLat !== 0 || rLng !== 0)) {
                this.state.latitude = rLat;
                this.state.longitude = rLng;
                this.state.hasPoints = true;
                this.state.isLive = true;
                this.state.statusText = "Live Tracking Active";
                this.state.googleMapsUrl = recData.track_map_url || `https://www.google.com/maps?q=${rLat},${rLng}`;
                if (recData.track_last_updated_at) {
                    this.state.lastUpdatedText = `Updated: ${recData.track_last_updated_at}`;
                }
            }
        }

        if (!this.employeeId) {
            this.state.loading = false;
            if (!this.state.latitude) {
                this.state.statusText = "Save record to enable live tracking map";
            }
            return;
        }

        try {
            this.state.loading = true;
            let data = null;

            // 1. Try standard ORM call first
            try {
                data = await this.orm.call("hr.employee", "get_today_location_logs", [this.employeeId]);
            } catch (_) {
                // 2. Fallback to HTTP JSON-RPC endpoint
                data = await rpc("/face_attendance/get_today_location_logs", {
                    employee_id: this.employeeId,
                });
            }

            if (data && data.status === "success") {
                this.locationData = data;
                const points = data.points || [];
                this.state.pointCount = points.length;
                this.state.hasPoints = points.length > 0 || Boolean(data.track_latitude && data.track_longitude);

                const latestLat = data.track_latitude || (points.length ? points[points.length - 1].latitude : null);
                const latestLng = data.track_longitude || (points.length ? points[points.length - 1].longitude : null);

                if (latestLat && latestLng) {
                    this.state.latitude = latestLat;
                    this.state.longitude = latestLng;
                    this.state.googleMapsUrl = data.track_map_url || `https://www.google.com/maps?q=${latestLat},${latestLng}`;
                    this.state.isLive = true;
                    this.state.statusText = "Live Tracking Active";
                    if (data.track_last_updated_at) {
                        this.state.lastUpdatedText = `Updated: ${data.track_last_updated_at}`;
                    } else if (points.length) {
                        this.state.lastUpdatedText = `Updated: ${points[points.length - 1].timestamp}`;
                    }
                    if (points.length) {
                        this.lastTimestamp = points[points.length - 1].timestamp;
                    }
                } else if (!this.state.latitude) {
                    this.state.isLive = false;
                    this.state.statusText = "No GPS locations logged today";
                    this.state.lastUpdatedText = "";
                    this.state.googleMapsUrl = "";
                }
            }
        } catch (err) {
            console.warn("Failed to load today's location logs:", err);
            if (!this.state.latitude) {
                this.state.statusText = "No GPS locations logged today";
            }
        } finally {
            this.state.loading = false;
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

        // Default view
        const initialLat = this.state.latitude || 20;
        const initialLng = this.state.longitude || 0;
        const initialZoom = this.state.hasPoints ? 16 : 2;
        this.map.setView([initialLat, initialLng], initialZoom);

        // Automatically trigger invalidateSize on resize or visibility change
        if (window.ResizeObserver && this.mapRef.el) {
            this.resizeObserver = new ResizeObserver(() => {
                if (this.map) {
                    this.map.invalidateSize();
                }
            });
            this.resizeObserver.observe(this.mapRef.el);
        }

        // Staggered size invalidations to ensure proper tile coverage after layout transitions
        setTimeout(() => this.map && this.map.invalidateSize(), 50);
        setTimeout(() => this.map && this.map.invalidateSize(), 200);
        setTimeout(() => this.map && this.map.invalidateSize(), 600);
    }

    renderRoute() {
        if (!this.map || !window.L) {
            return;
        }

        // Clear existing map layers
        if (this.startMarker) {
            this.startMarker.remove();
            this.startMarker = null;
        }
        if (this.currentMarker) {
            this.currentMarker.remove();
            this.currentMarker = null;
        }
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

        const points = this.locationData?.points || [];
        const latLngs = [];

        for (const p of points) {
            if (p.latitude && p.longitude) {
                latLngs.push([p.latitude, p.longitude]);
            }
        }

        // Fallback to employee's latest lat/long if no points array
        if (!latLngs.length && this.state.latitude && this.state.longitude) {
            latLngs.push([this.state.latitude, this.state.longitude]);
        }

        if (!latLngs.length) {
            this.map.setView([20, 0], 2);
            return;
        }

        // 1. Draw route polyline immediately as base/fallback
        if (latLngs.length > 1) {
            this.routePolyline = window.L.polyline(latLngs, {
                color: "#007bff",
                weight: 4,
                opacity: 0.85,
                lineJoin: "round",
            }).addTo(this.map);

            // Enhance with Leaflet Routing Machine road route
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
                        console.warn("Live route routing machine calculation warning:", e?.error || e);
                    });
                } catch (routingErr) {
                    console.warn("Live route routing machine skipped, fallback polyline active:", routingErr);
                }
            }

            // 2. Add Start Marker
            const startIcon = window.L.divIcon({
                className: "o_start_pin_wrapper",
                html: `<div class="o_start_pin_icon" title="Shift Start"><i class="fa fa-flag"></i></div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            });
            this.startMarker = window.L.marker(latLngs[0], { icon: startIcon })
                .bindPopup(`<b>Start Location</b><br/>Time: ${points[0]?.timestamp || "Start"}`)
                .addTo(this.map);
        }

        // 3. Add Current / Latest Live Marker
        const latestCoord = latLngs[latLngs.length - 1];
        const currentIcon = window.L.divIcon({
            className: "o_live_pin_wrapper",
            html: `<div class="o_live_pin_icon" title="Current Live Position"><i class="fa fa-user"></i></div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });

        this.currentMarker = window.L.marker(latestCoord, { icon: currentIcon })
            .bindPopup(`<b>${this.employeeName}</b><br/>Status: Live Location<br/>${this.state.lastUpdatedText}`)
            .addTo(this.map);

        // Fit map bounds to view all route waypoints with comfortable padding
        if (latLngs.length > 1) {
            const bounds = window.L.latLngBounds(latLngs);
            this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
        } else {
            this.map.setView(latestCoord, 16);
        }

        setTimeout(() => this.map && this.map.invalidateSize(), 100);
    }

    handleLiveCoordinate(payload) {
        if (!payload || !payload.latitude || !payload.longitude) {
            return;
        }

        const lat = parseFloat(payload.latitude);
        const lng = parseFloat(payload.longitude);
        if (isNaN(lat) || isNaN(lng)) {
            return;
        }

        this.state.latitude = lat;
        this.state.longitude = lng;
        this.state.isLive = true;
        this.state.hasPoints = true;
        this.state.statusText = "Live Tracking Active";
        this.state.lastUpdatedText = `Updated: ${payload.timestamp || "Just now"}`;
        this.state.googleMapsUrl = `https://www.google.com/maps?q=${lat},${lng}`;
        this.lastTimestamp = payload.timestamp;

        if (!this.map && this.mapRef.el && window.L) {
            this.initMap();
        }

        if (!this.map || !window.L) {
            return;
        }

        const newLatLng = [lat, lng];

        // Update or create current marker
        if (this.currentMarker) {
            this.currentMarker.setLatLng(newLatLng);
            this.currentMarker.setPopupContent(
                `<b>${this.employeeName}</b><br/>Status: Live Location<br/>${this.state.lastUpdatedText}`
            );
        } else {
            const currentIcon = window.L.divIcon({
                className: "o_live_pin_wrapper",
                html: `<div class="o_live_pin_icon" title="Current Live Position"><i class="fa fa-user"></i></div>`,
                iconSize: [28, 28],
                iconAnchor: [14, 14],
            });
            this.currentMarker = window.L.marker(newLatLng, { icon: currentIcon })
                .bindPopup(`<b>${this.employeeName}</b><br/>Status: Live Location<br/>${this.state.lastUpdatedText}`)
                .addTo(this.map);
        }

        // Append to route polyline
        if (this.routePolyline) {
            this.routePolyline.addLatLng(newLatLng);
        } else {
            this.routePolyline = window.L.polyline([newLatLng], {
                color: "#007bff",
                weight: 4,
                opacity: 0.85,
                lineJoin: "round",
            }).addTo(this.map);
        }

        // Smoothly pan map to new position
        this.map.panTo(newLatLng);
        setTimeout(() => this.map && this.map.invalidateSize(), 50);
    }

    setupLiveListeners() {
        if (!this.employeeId) {
            return;
        }

        // 1. Odoo Bus Service real-time WebSocket subscription
        if (this.busService) {
            const channel = `hr_employee_tracking_${this.employeeId}`;
            try {
                this.busService.addChannel(channel);
                this.busService.subscribe("hr_employee_tracking/update", (payload) => {
                    if (payload && payload.employee_id === this.employeeId) {
                        this.handleLiveCoordinate(payload);
                    }
                });
            } catch (busErr) {
                console.warn("Could not register bus listener for employee tracking:", busErr);
            }
        }

        // 2. Active 10-second polling heartbeat fallback
        this.pollInterval = setInterval(async () => {
            await this.checkForUpdates();
        }, 10000);
    }

    async checkForUpdates() {
        if (!this.employeeId || !this.map) {
            return;
        }
        try {
            let data = null;
            try {
                data = await this.orm.call("hr.employee", "get_today_location_logs", [this.employeeId]);
            } catch (_) {
                data = await rpc("/face_attendance/get_today_location_logs", {
                    employee_id: this.employeeId,
                });
            }

            if (data && data.status === "success") {
                const points = data.points || [];
                const latestLat = data.track_latitude || (points.length ? points[points.length - 1].latitude : null);
                const latestLng = data.track_longitude || (points.length ? points[points.length - 1].longitude : null);
                const latestTime = data.track_last_updated_at || (points.length ? points[points.length - 1].timestamp : null);

                // If coordinates or timestamp have changed, update map
                if (latestLat && latestLng && (latestLat !== this.state.latitude || latestLng !== this.state.longitude || latestTime !== this.lastTimestamp)) {
                    this.locationData = data;
                    this.handleLiveCoordinate({
                        employee_id: this.employeeId,
                        latitude: latestLat,
                        longitude: latestLng,
                        timestamp: latestTime,
                    });
                }
            }
        } catch (_) {}
    }

    recenterMap() {
        if (this.map && this.state.latitude && this.state.longitude) {
            this.map.setView([this.state.latitude, this.state.longitude], 16);
            if (this.currentMarker) {
                this.currentMarker.openPopup();
            }
            setTimeout(() => this.map && this.map.invalidateSize(), 50);
        }
    }

    async reloadLogs() {
        await this.loadLocationData();
        this.renderRoute();
    }

    cleanup() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
        if (this.startMarker) {
            this.startMarker.remove();
            this.startMarker = null;
        }
        if (this.currentMarker) {
            this.currentMarker.remove();
            this.currentMarker = null;
        }
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
        if (this.map) {
            this.map.remove();
            this.map = null;
        }
    }
}

export const employeeLiveTrackingMapWidget = {
    component: EmployeeLiveTrackingMap,
};

registry.category("view_widgets").add("employee_live_tracking_map", employeeLiveTrackingMapWidget);
