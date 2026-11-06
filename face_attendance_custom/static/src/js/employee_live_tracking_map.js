/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useService } from "@web/core/utils/hooks";
import { loadCSS, loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState, useEffect } from "@odoo/owl";
import { processRoutePoints, snapToRoadsOSRM } from "./route_geometry_utils";

const LEAFLET_LOCAL_CSS = "/face_attendance_custom/static/lib/leaflet/leaflet.css";
const LEAFLET_LOCAL_JS = "/face_attendance_custom/static/lib/leaflet/leaflet.js";
const LEAFLET_CDN_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_CDN_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";

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
        this.routeGlowPolyline = null;
        this.routeCorePolyline = null;
        this.pollInterval = null;
        this.resizeObserver = null;
        this.lastTimestamp = null;
        this.locationData = null;
        this.processedData = null;
        this.snappedCoords = null;

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
            pathMode: "smooth",
            distanceText: "",
            snappingRoad: false,
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
            () => [
                this.props.record?.resId,
                this.props.record?.data?.track_employee,
                this.props.record?.data?.attendance_state,
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
                    console.warn("Could not load Leaflet map assets:", cdnErr);
                }
            }
        }
    }

    get employeeId() {
        return this.props.record?.resId || false;
    }

    get employeeName() {
        return this.props.record?.data?.name || "Employee";
    }

    getIsCheckedIn(source = {}) {
        if (source && typeof source.is_checked_in === "boolean") {
            return source.is_checked_in;
        }
        if (source && source.attendance_state) {
            return source.attendance_state === "checked_in";
        }
        if (this.props.record?.data?.attendance_state) {
            return this.props.record.data.attendance_state === "checked_in";
        }
        return false;
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
                const isCheckedIn = this.getIsCheckedIn(recData);
                this.state.isLive = isCheckedIn;
                this.state.statusText = isCheckedIn ? "Live Tracking Active" : "Checked out";
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

                const isCheckedIn = this.getIsCheckedIn(data);
                const latestLat = data.track_latitude || (points.length ? points[points.length - 1].latitude : null);
                const latestLng = data.track_longitude || (points.length ? points[points.length - 1].longitude : null);

                if (latestLat && latestLng) {
                    this.state.latitude = latestLat;
                    this.state.longitude = latestLng;
                    this.state.googleMapsUrl = data.track_map_url || `https://www.google.com/maps?q=${latestLat},${latestLng}`;
                    this.state.isLive = isCheckedIn;
                    this.state.statusText = isCheckedIn ? "Live Tracking Active" : "Checked out";
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
                    this.state.statusText = isCheckedIn ? "No GPS locations logged today" : "Checked out";
                    this.state.lastUpdatedText = "";
                    this.state.googleMapsUrl = "";
                }
            }
        } catch (err) {
            console.warn("Failed to load today's location logs:", err);
            if (!this.state.latitude) {
                const isCheckedIn = this.getIsCheckedIn(recData);
                this.state.statusText = isCheckedIn ? "No GPS locations logged today" : "Checked out";
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

    clearRouteLayers() {
        if (this.routeGlowPolyline) {
            this.routeGlowPolyline.remove();
            this.routeGlowPolyline = null;
        }
        if (this.routeCorePolyline) {
            this.routeCorePolyline.remove();
            this.routeCorePolyline = null;
        }
    }

    async setPathMode(mode) {
        if (this.state.pathMode === mode) return;
        this.state.pathMode = mode;

        if (mode === "snap" && !this.snappedCoords && this.processedData?.cleanedCoords?.length > 1) {
            this.state.snappingRoad = true;
            try {
                this.snappedCoords = await snapToRoadsOSRM(this.processedData.cleanedCoords);
            } catch (_) {
                this.snappedCoords = null;
            } finally {
                this.state.snappingRoad = false;
            }
        }
        this.drawRoutePolylines();
    }

    getActiveRouteCoordinates() {
        if (!this.processedData) return [];
        if (this.state.pathMode === "raw") {
            return this.processedData.rawCoords || [];
        }
        if (this.state.pathMode === "snap" && this.snappedCoords && this.snappedCoords.length > 1) {
            return this.snappedCoords;
        }
        return this.processedData.smoothedCoords || this.processedData.rawCoords || [];
    }

    drawRoutePolylines() {
        if (!this.map || !window.L) return;
        this.clearRouteLayers();

        const activeCoords = this.getActiveRouteCoordinates();
        if (activeCoords.length > 1) {
            // 1. Glowing outer halo
            this.routeGlowPolyline = window.L.polyline(activeCoords, {
                color: "#3b82f6",
                weight: 7,
                opacity: 0.28,
                lineCap: "round",
                lineJoin: "round",
            }).addTo(this.map);

            // 2. Crisp, vibrant core line
            this.routeCorePolyline = window.L.polyline(activeCoords, {
                color: "#2563eb",
                weight: 3.5,
                opacity: 0.95,
                lineCap: "round",
                lineJoin: "round",
            }).addTo(this.map);
        }
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
        this.clearRouteLayers();

        const points = this.locationData?.points || [];
        this.processedData = processRoutePoints(points);

        if (this.processedData.totalDistanceKm > 0) {
            this.state.distanceText = `${this.processedData.totalDistanceKm.toFixed(2)} km`;
        } else {
            this.state.distanceText = "";
        }

        const rawCoords = this.processedData.rawCoords || [];

        // Fallback to employee's latest lat/long if no points array
        if (!rawCoords.length && this.state.latitude && this.state.longitude) {
            rawCoords.push([this.state.latitude, this.state.longitude]);
        }

        if (!rawCoords.length) {
            this.map.setView([20, 0], 2);
            return;
        }

        // Draw dual-layer polyline
        this.drawRoutePolylines();

        // Add Start Marker
        if (rawCoords.length > 1) {
            const startIcon = window.L.divIcon({
                className: "o_start_pin_wrapper",
                html: `<div class="o_start_pin_icon" title="Shift Start"><i class="fa fa-flag"></i></div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
            });
            this.startMarker = window.L.marker(rawCoords[0], { icon: startIcon })
                .bindPopup(`<b>Start Location</b><br/>Time: ${points[0]?.timestamp || "Start"}`)
                .addTo(this.map);
        }

        // Add Current / Latest Live Marker
        const latestCoord = rawCoords[rawCoords.length - 1];
        const currentIcon = window.L.divIcon({
            className: "o_live_pin_wrapper",
            html: `<div class="o_live_pin_icon" title="Current Live Position"><i class="fa fa-user"></i></div>`,
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });

        const statusLabel = this.state.isLive ? "Live Location" : "Checked out";
        this.currentMarker = window.L.marker(latestCoord, { icon: currentIcon })
            .bindPopup(`<b>${this.employeeName}</b><br/>Status: ${statusLabel}<br/>${this.state.lastUpdatedText}`)
            .addTo(this.map);

        // Fit map bounds to view all route waypoints with comfortable padding
        const activeCoords = this.getActiveRouteCoordinates();
        const fitCoords = activeCoords.length > 1 ? activeCoords : rawCoords;
        if (fitCoords.length > 1) {
            const bounds = window.L.latLngBounds(fitCoords);
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

        const isCheckedIn = this.getIsCheckedIn(payload);
        this.state.latitude = lat;
        this.state.longitude = lng;
        this.state.isLive = isCheckedIn;
        this.state.hasPoints = true;
        this.state.statusText = isCheckedIn ? "Live Tracking Active" : "Checked out";
        this.state.lastUpdatedText = `Updated: ${payload.timestamp || "Just now"}`;
        this.state.googleMapsUrl = `https://www.google.com/maps?q=${lat},${lng}`;
        this.lastTimestamp = payload.timestamp;

        // Invalidate cached snapped coords on new live data
        this.snappedCoords = null;

        if (!this.locationData) {
            this.locationData = { points: [] };
        }
        if (!this.locationData.points) {
            this.locationData.points = [];
        }
        this.locationData.points.push({
            latitude: lat,
            longitude: lng,
            timestamp: payload.timestamp || new Date().toISOString(),
        });
        this.state.pointCount = this.locationData.points.length;

        if (!this.map && this.mapRef.el && window.L) {
            this.initMap();
        }

        if (!this.map || !window.L) {
            return;
        }

        // Re-process route with latest coordinate through smoothing pipeline
        this.renderRoute();

        // Smoothly pan map to new position
        this.map.panTo([lat, lng]);
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

                const isCheckedIn = this.getIsCheckedIn(data);
                this.state.isLive = isCheckedIn;
                if (this.state.hasPoints) {
                    this.state.statusText = isCheckedIn ? "Live Tracking Active" : "Checked out";
                    if (this.currentMarker) {
                        const statusLabel = isCheckedIn ? "Live Location" : "Checked out";
                        this.currentMarker.setPopupContent(
                            `<b>${this.employeeName}</b><br/>Status: ${statusLabel}<br/>${this.state.lastUpdatedText}`
                        );
                    }
                }

                // If coordinates or timestamp have changed, update map
                if (latestLat && latestLng && (latestLat !== this.state.latitude || latestLng !== this.state.longitude || latestTime !== this.lastTimestamp)) {
                    this.locationData = data;
                    this.handleLiveCoordinate({
                        employee_id: this.employeeId,
                        latitude: latestLat,
                        longitude: latestLng,
                        timestamp: latestTime,
                        is_checked_in: isCheckedIn,
                        attendance_state: data.attendance_state,
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
        this.clearRouteLayers();
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
