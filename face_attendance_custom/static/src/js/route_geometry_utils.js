/** @odoo-module **/

/**
 * Calculates Haversine distance in meters between two lat/lng coordinates.
 */
export function haversineDistance(lat1, lon1, lat2, lon2) {
    const R = 6371000; // Earth radius in meters
    const toRad = Math.PI / 180;
    const dLat = (lat2 - lat1) * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
        Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

/**
 * Calculates the interior angle (in degrees) at vertex B for triangle A-B-C.
 */
export function calculateTurnAngle(pA, pB, pC) {
    const a = haversineDistance(pB[0], pB[1], pC[0], pC[1]);
    const b = haversineDistance(pA[0], pA[1], pC[0], pC[1]);
    const c = haversineDistance(pA[0], pA[1], pB[0], pB[1]);

    if (a === 0 || c === 0) return 180;
    const cosB = (a * a + c * c - b * b) / (2 * a * c);
    const clampedCos = Math.max(-1, Math.min(1, cosB));
    return (Math.acos(clampedCos) * 180) / Math.PI;
}

/**
 * Stage 1 & 2: Despikes outlier waypoints.
 * Eliminates:
 * 1. Teleportation / speed anomalies (> 25 m/s or 90 km/h walking).
 * 2. Acute lateral bounces into alleys/buildings (A -> B -> C where B is an acute spike and returns immediately).
 */
export function filterOutlierSpikes(rawPoints) {
    if (!rawPoints || rawPoints.length <= 2) {
        return rawPoints || [];
    }

    // Step 1: Filter out impossible speed jumps if timestamps exist
    const speedFiltered = [rawPoints[0]];
    for (let i = 1; i < rawPoints.length; i++) {
        const prev = speedFiltered[speedFiltered.length - 1];
        const curr = rawPoints[i];

        const dist = haversineDistance(prev.latitude, prev.longitude, curr.latitude, curr.longitude);
        if (prev.timestamp && curr.timestamp) {
            const t1 = new Date(prev.timestamp).getTime();
            const t2 = new Date(curr.timestamp).getTime();
            const dtSec = Math.abs(t2 - t1) / 1000;
            if (dtSec > 0 && dist / dtSec > 30) {
                // Impossible jump (> 108 km/h), skip outlier
                continue;
            }
        }
        speedFiltered.push(curr);
    }

    if (speedFiltered.length <= 2) {
        return speedFiltered;
    }

    // Step 2: Remove acute bounce spikes (A -> B -> C where B juts sideways into a building and returns)
    const despiked = [speedFiltered[0]];
    for (let i = 1; i < speedFiltered.length - 1; i++) {
        const prev = despiked[despiked.length - 1];
        const curr = speedFiltered[i];
        const next = speedFiltered[i + 1];

        const pA = [prev.latitude, prev.longitude];
        const pB = [curr.latitude, curr.longitude];
        const pC = [next.latitude, next.longitude];

        const dAB = haversineDistance(pA[0], pA[1], pB[0], pB[1]);
        const dBC = haversineDistance(pB[0], pB[1], pC[0], pC[1]);
        const dAC = haversineDistance(pA[0], pA[1], pC[0], pC[1]);

        // Acute lateral detour: detour distance is significantly greater than direct path
        // and direct path is short (< 50m) or interior angle is sharp (< 55 deg)
        const isAcuteTurn = calculateTurnAngle(pA, pB, pC) < 55;
        const isExcessiveDetour = dAC > 0 && (dAB + dBC) / dAC > 2.0;

        if ((isAcuteTurn || isExcessiveDetour) && dAB > 6 && dBC > 6 && dAC < 60) {
            // Discard point B
            continue;
        }

        despiked.push(curr);
    }

    despiked.push(speedFiltered[speedFiltered.length - 1]);
    return despiked;
}

/**
 * Stage 3: Eliminates stationary wandering / clusters.
 * When an employee is paused, stationary, or inside a shop, GPS fluctuates in a 5-10m cloud.
 * This collapses clusters into a single anchor point, preventing hairpin zig-zag nests.
 */
export function filterStationaryDrift(points, minDistanceMeters = 8) {
    if (!points || points.length <= 1) {
        return points || [];
    }

    const filtered = [points[0]];
    for (let i = 1; i < points.length; i++) {
        const curr = points[i];
        const last = filtered[filtered.length - 1];
        const dist = haversineDistance(last.latitude, last.longitude, curr.latitude, curr.longitude);

        if (dist >= minDistanceMeters) {
            filtered.push(curr);
        }
    }

    // Always preserve latest/current location if distinct
    const finalPoint = points[points.length - 1];
    const lastFiltered = filtered[filtered.length - 1];
    const distToLast = haversineDistance(lastFiltered.latitude, lastFiltered.longitude, finalPoint.latitude, finalPoint.longitude);
    if (distToLast >= 3 && (lastFiltered.latitude !== finalPoint.latitude || lastFiltered.longitude !== finalPoint.longitude)) {
        filtered.push(finalPoint);
    }

    return filtered;
}

/**
 * Douglas-Peucker line simplification.
 * Prunes collinear micro-variations within epsilon tolerance meters.
 */
export function douglasPeucker(latLngs, epsilonMeters = 2.5) {
    if (!latLngs || latLngs.length <= 2) {
        return latLngs || [];
    }

    function perpendicularDistance(p, p1, p2) {
        const d12 = haversineDistance(p1[0], p1[1], p2[0], p2[1]);
        if (d12 === 0) return haversineDistance(p[0], p[1], p1[0], p1[1]);

        const d1 = haversineDistance(p1[0], p1[1], p[0], p[1]);
        const d2 = haversineDistance(p2[0], p2[1], p[0], p[1]);

        // Semi-perimeter
        const s = (d1 + d2 + d12) / 2;
        const area = Math.sqrt(Math.max(0, s * (s - d1) * (s - d2) * (s - d12)));
        return (2 * area) / d12;
    }

    function dpRecursive(list) {
        if (list.length <= 2) return list;

        let maxDist = 0;
        let maxIndex = 0;
        const pFirst = list[0];
        const pLast = list[list.length - 1];

        for (let i = 1; i < list.length - 1; i++) {
            const dist = perpendicularDistance(list[i], pFirst, pLast);
            if (dist > maxDist) {
                maxDist = dist;
                maxIndex = i;
            }
        }

        if (maxDist > epsilonMeters) {
            const left = dpRecursive(list.slice(0, maxIndex + 1));
            const right = dpRecursive(list.slice(maxIndex));
            return left.slice(0, -1).concat(right);
        } else {
            return [pFirst, pLast];
        }
    }

    return dpRecursive(latLngs);
}

/**
 * Stage 4: Chaikin's Corner-Cutting Smoothing Algorithm.
 * Rounds polygonal corners into smooth, flowing curves suitable for map rendering.
 */
export function chaikinSmooth(latLngs, iterations = 2) {
    if (!latLngs || latLngs.length <= 2) {
        return latLngs || [];
    }

    let current = latLngs;
    for (let it = 0; it < iterations; it++) {
        const smoothed = [current[0]];
        for (let i = 0; i < current.length - 1; i++) {
            const p0 = current[i];
            const p1 = current[i + 1];

            // Q = 0.75 P0 + 0.25 P1
            const q = [
                0.75 * p0[0] + 0.25 * p1[0],
                0.75 * p0[1] + 0.25 * p1[1],
            ];
            // R = 0.25 P0 + 0.75 P1
            const r = [
                0.25 * p0[0] + 0.75 * p1[0],
                0.25 * p0[1] + 0.75 * p1[1],
            ];

            smoothed.push(q);
            smoothed.push(r);
        }
        smoothed.push(current[current.length - 1]);
        current = smoothed;
    }

    return current;
}

/**
 * Snaps coordinates to the OpenStreetMap road network via public OSRM Match API.
 * Returns null if network fails or match confidence is low.
 */
export async function snapToRoadsOSRM(latLngs, profile = "walking") {
    if (!latLngs || latLngs.length < 2) {
        return null;
    }

    // OSRM match limits coordinate count per request; sample down if necessary
    let sample = latLngs;
    if (latLngs.length > 80) {
        const step = Math.ceil(latLngs.length / 80);
        sample = latLngs.filter((_, idx) => idx % step === 0 || idx === latLngs.length - 1);
    }

    // Coordinates formatted as: {lng},{lat};{lng},{lat}
    const coordsStr = sample.map(p => `${p[1].toFixed(6)},${p[0].toFixed(6)}`).join(";");
    const url = `https://router.project-osrm.org/match/v1/${profile}/${coordsStr}?overview=full&geometries=geojson`;

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 4000); // 4s timeout

        const resp = await fetch(url, { signal: controller.signal });
        clearTimeout(timeoutId);

        if (!resp.ok) return null;
        const data = await resp.json();

        if (data.code === "Ok" && data.matchings && data.matchings.length > 0) {
            const matchedCoords = [];
            for (const matching of data.matchings) {
                if (matching.geometry && matching.geometry.coordinates) {
                    for (const coord of matching.geometry.coordinates) {
                        // GeoJSON is [lng, lat], Leaflet is [lat, lng]
                        matchedCoords.push([coord[1], coord[0]]);
                    }
                }
            }
            return matchedCoords.length > 1 ? matchedCoords : null;
        }
    } catch (_) {
        // Fallback gracefully on timeout, offline, or CORS
    }

    return null;
}

/**
 * Computes total path distance in kilometers.
 */
export function calculatePathDistanceKm(latLngs) {
    if (!latLngs || latLngs.length < 2) return 0;
    let totalMeters = 0;
    for (let i = 0; i < latLngs.length - 1; i++) {
        totalMeters += haversineDistance(
            latLngs[i][0], latLngs[i][1],
            latLngs[i + 1][0], latLngs[i + 1][1]
        );
    }
    return totalMeters / 1000;
}

/**
 * Master pipeline: Cleans and smooths raw points.
 * Returns { rawCoords, smoothedCoords, totalDistanceKm }
 */
export function processRoutePoints(rawPoints) {
    if (!rawPoints || !rawPoints.length) {
        return { rawCoords: [], smoothedCoords: [], totalDistanceKm: 0 };
    }

    // 1. Extract valid coordinates
    const valid = [];
    for (const p of rawPoints) {
        if (p && typeof p.latitude === "number" && typeof p.longitude === "number") {
            if (p.latitude !== 0 || p.longitude !== 0) {
                valid.push(p);
            }
        }
    }

    if (!valid.length) {
        return { rawCoords: [], smoothedCoords: [], totalDistanceKm: 0 };
    }

    const rawCoords = valid.map(p => [p.latitude, p.longitude]);
    if (valid.length === 1) {
        return { rawCoords, smoothedCoords: rawCoords, totalDistanceKm: 0 };
    }

    // 2. Stage 1 & 2: Despike lateral multipaths and speed anomalies
    const despiked = filterOutlierSpikes(valid);

    // 3. Stage 3: Stationary cluster deadband
    const stationaryFiltered = filterStationaryDrift(despiked, 8);

    // 4. Convert to [lat, lng]
    const cleanedLatLngs = stationaryFiltered.map(p => [p.latitude, p.longitude]);

    // 5. Stage 4: Douglas-Peucker simplification
    const simplified = douglasPeucker(cleanedLatLngs, 2.5);

    // 6. Stage 5: Chaikin curve smoothing
    const smoothedCoords = chaikinSmooth(simplified, 2);

    const totalDistanceKm = calculatePathDistanceKm(cleanedLatLngs);

    return {
        rawCoords,
        cleanedCoords: cleanedLatLngs,
        smoothedCoords,
        totalDistanceKm,
    };
}
