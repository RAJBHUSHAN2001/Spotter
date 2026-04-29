/**
 * Spotter: Smart Fuel Route Planner
 * Frontend Controller (app.js)
 * 
 * Manages the interactive map, real-time routing logic, 
 * and dual-strategy UI state synchronization.
 */

// ─────────────────────────────────────────────────────────────────────────────
// GLOBAL STATE & CORE COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

const map = L.map('map').setView([39.8283, -98.5795], 4);
let currentTileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
}).addTo(map);

let routeLayerFastest = null;
let routeLayerMaxSave = null;
let markerLayer = L.layerGroup().addTo(map);
let popupLayer = null;
let currentData = null;
let currentStrategy = 'max_save';

// ─────────────────────────────────────────────────────────────────────────────
// CONTEXT MENU & REVERSE GEOCODING
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Handle map clicks by snapping to the nearest drivable road via OSRM 
 * and offering a context menu to set the start or end point.
 */
map.on('click', async (e) => {
    const { lat, lng: lon } = e.latlng;
    popupLayer = L.popup()
        .setLatLng(e.latlng)
        .setContent(`
            <div style="padding:10px;min-width:160px;">
                <p style="font-weight:700;font-size:0.85rem;margin-bottom:8px;">Set this location as:</p>
                <button onclick="setMapLocation('start', ${lat}, ${lon})" style="width:100%;background:#10b981;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:0.8rem;cursor:pointer;margin-bottom:6px;font-weight:600;">🏁 Start</button>
                <button onclick="setMapLocation('end', ${lat}, ${lon})" style="width:100%;background:#ef4444;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:0.8rem;cursor:pointer;font-weight:600;">📍 End</button>
            </div>`)
        .openOn(map);
});

window.setMapLocation = async (type, lat, lon) => {
    if (popupLayer) map.closePopup(popupLayer);
    try {
        const res = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=18`);
        const data = await res.json();
        let address = 'Selected on Map';
        let snappedLat = lat, snappedLon = lon;
        if (data?.address) {
            const city = data.address.city || data.address.town || data.address.village || data.address.county;
            address = city ? `${city}, ${data.address.state}` : data.display_name.split(',').slice(0, 2).join(',');
            if (data.lat && data.lon) { snappedLat = parseFloat(data.lat); snappedLon = parseFloat(data.lon); }
        }
        try {
            const osrmRes = await fetch(`https://router.project-osrm.org/nearest/v1/driving/${snappedLon},${snappedLat}`);
            const od = await osrmRes.json();
            if (od.code === 'Ok' && od.waypoints?.length) { snappedLon = od.waypoints[0].location[0]; snappedLat = od.waypoints[0].location[1]; }
        } catch {}
        if (type === 'start') {
            document.getElementById('startInput').value = address;
            startCoords = [snappedLon, snappedLat];
            if (window.tempStartMarker) map.removeLayer(window.tempStartMarker);
            window.tempStartMarker = L.marker([snappedLat, snappedLon]).addTo(map).bindPopup(`<b>Start</b><br>${address}`).openPopup();
        } else {
            document.getElementById('endInput').value = address;
            endCoords = [snappedLon, snappedLat];
            if (window.tempEndMarker) map.removeLayer(window.tempEndMarker);
            window.tempEndMarker = L.marker([snappedLat, snappedLon]).addTo(map).bindPopup(`<b>End</b><br>${address}`).openPopup();
        }
    } catch (e) { console.error('Reverse geocode failed', e); }
};

// ─────────────────────────────────────────
// Fuel display
// ─────────────────────────────────────────
let startCoords = null, endCoords = null;

function updateFuelDisplay() {
    const val = parseFloat(document.getElementById('startingFuel').value) || 0;
    const unit = document.getElementById('fuelUnit').value;
    const gallons = unit === 'gallons' ? val : (val / 100) * 50;
    const liters = (gallons * 3.78541).toFixed(1);
    document.getElementById('litersDisplay').textContent = unit === 'gallons' ? `${liters} L` : `${liters} L (${gallons.toFixed(1)} gal)`;
}

document.getElementById('startingFuel').addEventListener('input', updateFuelDisplay);
document.getElementById('fuelUnit').addEventListener('change', (e) => {
    const input = document.getElementById('startingFuel');
    const val = parseFloat(input.value) || 0;
    if (e.target.value === 'percent') { input.max = 100; input.value = Math.round((val / 50) * 100); }
    else { input.max = 50; input.value = Math.round((val / 100) * 50); }
    updateFuelDisplay();
});

document.getElementById('priceSlider').addEventListener('input', (e) => {
    document.getElementById('priceFilterVal').textContent = `$${parseFloat(e.target.value).toFixed(2)}`;
    if (currentData) renderMarkers(currentData, parseFloat(e.target.value));
});

// ─────────────────────────────────────────
// Strategy toggles
// ─────────────────────────────────────────
const activeTabCls = 'flex-1 bg-white dark:bg-gray-700 text-emerald-600 dark:text-emerald-400 py-1.5 rounded-md shadow-sm text-sm font-bold transition-all border border-slate-200 dark:border-gray-600';
const inactiveTabCls = 'flex-1 text-slate-500 dark:text-gray-400 hover:text-slate-800 dark:hover:text-gray-200 py-1.5 rounded-md text-sm font-medium transition-all';

document.getElementById('toggleMaxSave').addEventListener('click', () => {
    currentStrategy = 'max_save';
    document.getElementById('toggleMaxSave').className = activeTabCls;
    document.getElementById('toggleFastest').className = inactiveTabCls;
    if (currentData) updateStrategy();
});

document.getElementById('toggleFastest').addEventListener('click', () => {
    currentStrategy = 'fastest';
    document.getElementById('toggleFastest').className = activeTabCls;
    document.getElementById('toggleMaxSave').className = inactiveTabCls;
    if (currentData) updateStrategy();
});

// ─────────────────────────────────────────
// Find Route
// ─────────────────────────────────────────
document.getElementById('findRouteBtn').addEventListener('click', async () => {
    const start = document.getElementById('startInput').value.trim();
    const end = document.getElementById('endInput').value.trim();
    const fuelVal = parseFloat(document.getElementById('startingFuel').value);
    const unit = document.getElementById('fuelUnit').value;
    const startingFuelPct = unit === 'gallons' ? (fuelVal / 50) * 100 : fuelVal;
    const errorMsg = document.getElementById('errorMsg');
    const loadingOverlay = document.getElementById('loadingOverlay');

    if (!start || !end) {
        errorMsg.textContent = 'Please enter both start and end locations.';
        errorMsg.classList.remove('hidden');
        return;
    }
    errorMsg.classList.add('hidden');
    loadingOverlay.classList.remove('hidden');

    try {
        const res = await fetch('http://localhost:8000/api/route/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start, end, start_coords: startCoords, end_coords: endCoords, starting_fuel_pct: startingFuelPct })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to calculate route');
        currentData = data;
        renderData(data);
    } catch (e) {
        errorMsg.textContent = e.message;
        errorMsg.classList.remove('hidden');
    } finally {
        loadingOverlay.classList.add('hidden');
    }
});

// Input Card Expansion
document.getElementById('inputMinimized').onclick = () => {
    document.getElementById('inputMinimized').classList.add('hidden');
    document.getElementById('inputExpanded').classList.remove('hidden');
};

// ─────────────────────────────────────────
// Render (initial load — draws routes + fits map)
// ─────────────────────────────────────────
function renderData(data) {
    // 1. Force UI Visibility Immediately
    document.getElementById('tripSummary').classList.remove('hidden');
    const sc = document.getElementById('stopsContainer');
    sc.classList.remove('hidden');
    sc.classList.add('flex');
    document.getElementById('algoInsights').classList.remove('hidden');

    // Minimize input card
    document.getElementById('inputExpanded').classList.add('hidden');
    document.getElementById('inputMinimized').classList.remove('hidden');
    document.getElementById('minimizedRouteInfo').textContent = `${data.trip.start.split(',')[0]} to ${data.trip.end.split(',')[0]}`;

    if (routeLayerFastest) map.removeLayer(routeLayerFastest);
    if (routeLayerMaxSave) map.removeLayer(routeLayerMaxSave);

    const fastestIsActive = currentStrategy === 'fastest';

    routeLayerMaxSave = L.polyline(data.max_save.polyline, {
        color: '#10b981',
        weight: fastestIsActive ? 3 : 5,
        opacity: fastestIsActive ? 0.45 : 1,
        dashArray: fastestIsActive ? '10, 10' : null,
        lineCap: 'round',
        lineJoin: 'round'
    }).addTo(map);

    routeLayerFastest = L.polyline(data.fastest.polyline, {
        color: '#fbbf24',
        weight: fastestIsActive ? 5 : 4,
        opacity: fastestIsActive ? 1 : 0.55,
        dashArray: fastestIsActive ? null : '10, 10',
        lineCap: 'round',
        lineJoin: 'round'
    }).addTo(map);

    fastestIsActive ? routeLayerFastest.bringToFront() : routeLayerMaxSave.bringToFront();
    map.fitBounds(routeLayerMaxSave.getBounds(), { padding: [40, 40] });

    updateMapLegend();
    renderMarkers(data, parseFloat(document.getElementById('priceSlider').value));
    refreshSummary(data);
}

// ─────────────────────────────────────────
// Update strategy (toggle only — NO fitBounds, NO polyline redraw)
// Just re-styles existing polylines, refreshes markers + summary
// ─────────────────────────────────────────
function updateStrategy() {
    const fastestIsActive = currentStrategy === 'fastest';

    // Re-style existing polylines in-place (no remove/re-add)
    if (routeLayerMaxSave) {
        routeLayerMaxSave.setStyle({ 
            weight: fastestIsActive ? 3 : 5, 
            opacity: fastestIsActive ? 0.45 : 1,
            dashArray: fastestIsActive ? '10, 10' : null,
            lineCap: 'round',
            lineJoin: 'round'
        });
    }
    if (routeLayerFastest) {
        routeLayerFastest.setStyle({ 
            weight: fastestIsActive ? 5 : 4, 
            opacity: fastestIsActive ? 1 : 0.55,
            dashArray: fastestIsActive ? null : '10, 10',
            lineCap: 'round',
            lineJoin: 'round'
        });
    }
    fastestIsActive ? routeLayerFastest.bringToFront() : routeLayerMaxSave.bringToFront();

    updateMapLegend();
    renderMarkers(currentData, parseFloat(document.getElementById('priceSlider').value));
    refreshSummary(currentData);
}

// ─────────────────────────────────────────
// Refresh summary panel (strategy-dependent fields only)
// ─────────────────────────────────────────
function refreshSummary(data) {
    const active = data[currentStrategy];
    const km = (data.trip.total_miles * 1.60934).toFixed(0);
    const liters = (data.trip.total_gallons * 3.78541).toFixed(1);

    document.getElementById('sumMiles').innerHTML    = `${data.trip.total_miles} <span class="text-xs font-normal text-slate-400">mi / ${km} km</span>`;
    document.getElementById('sumTime').textContent   = active.travel_time || data.trip.travel_time || '—';
    document.getElementById('sumGallons').innerHTML  = `${data.trip.total_gallons} <span class="text-xs font-normal text-slate-400">gal / ${liters} L</span>`;
    document.getElementById('sumStops').innerHTML    = `${active.fuel_stops.length} <span class="text-xs font-normal text-slate-400">stop${active.fuel_stops.length !== 1 ? 's' : ''}</span>`;
    document.getElementById('naiveCostCard').textContent = data.trip.naive_cost_display;
    document.getElementById('sumCost').textContent   = active.total_cost_display;
    document.getElementById('sumSaved').textContent  = active.money_saved;
    document.getElementById('stopCount').textContent = `${active.fuel_stops.length} stop${active.fuel_stops.length !== 1 ? 's' : ''}`;

    // Algorithm Insights (Strategy Specific)
    const ins = active.insights;
    document.getElementById('insightConsidered').textContent      = ins.stations_considered;
    document.getElementById('insightOnRoute').textContent         = ins.stations_on_route;
    document.getElementById('insightDetourEval').textContent      = ins.detours_evaluated;
    document.getElementById('insightDetourTaken').textContent     = ins.detours_taken;
    
    document.getElementById('insightEfficiency').textContent      = `Score: ${ins.efficiency_score}%`;
    document.getElementById('insightSavingsPerGallon').textContent = `$${ins.avg_savings_per_gallon.toFixed(3)}`;
    document.getElementById('insightVolatility').textContent      = ins.price_volatility.toFixed(3);
    document.getElementById('insightCheapestState').textContent   = ins.cheapest_state;
    document.getElementById('insightDetourMiles').textContent     = `${ins.total_detour_miles} mi`;
    
    // Hidden trackers
    document.getElementById('insightRejected').textContent        = ins.stations_rejected_expensive;
    document.getElementById('insightDetourRejected').textContent  = ins.detours_rejected;
}

function renderMarkers(data, maxPrice) {
    markerLayer.clearLayers();
    if (window.tempStartMarker) { map.removeLayer(window.tempStartMarker); window.tempStartMarker = null; }
    if (window.tempEndMarker) { map.removeLayer(window.tempEndMarker); window.tempEndMarker = null; }

    addMapMarker(data.route.start_coords, 'marker-green', '🏁 Start', data.trip.start);
    addMapMarker(data.route.end_coords, 'marker-red', '📍 End', data.trip.end);

    const stopsList = document.getElementById('stopsList');
    stopsList.innerHTML = '';

    const activeData = data ? data[currentStrategy] : null;
    if (!activeData || !activeData.fuel_stops) {
        stopsList.innerHTML = `<div class="p-4 text-center text-xs text-slate-400">Waiting for route data...</div>`;
        return;
    }

    activeData.fuel_stops.forEach((stop) => {
        if (stop.price_per_gallon > maxPrice) return;

        const arrivePct = Math.round((stop.tank_on_arrival_miles / 500) * 100);
        const departPct = Math.round((stop.tank_on_departure_miles / 500) * 100);
        const arriveColor = arrivePct < 20 ? 'text-red-500 dark:text-red-400' : arrivePct < 35 ? 'text-orange-500 dark:text-orange-400' : 'text-slate-700 dark:text-gray-200';
        const isDetour = stop.detour_taken;
        const isCheapest = stop.is_cheapest_overall;

        // Marker
        const iconHtml = isCheapest
            ? `<div class="marker-pin marker-gold">⭐</div>`
            : `<div class="marker-pin ${isDetour ? 'marker-orange' : 'marker-yellow'}">${stop.order}</div>`;

        const popupContent = `
            <div style="padding:10px;width:230px;font-family:inherit;">
                <div style="font-weight:700;font-size:0.85rem;margin-bottom:4px;line-height:1.3;">${stop.name}</div>
                <div style="font-size:0.7rem;margin-bottom:8px;opacity:0.65;">📍 ${stop.city}, ${stop.state} · Mile ${stop.miles_along_route}</div>
                ${isDetour ? `<div style="font-size:0.7rem;color:#f97316;margin-bottom:8px;">⤵ Detour: ${stop.miles_from_route} mi off route</div>` : ''}
                <div style="background:rgba(0,0,0,0.06);border-radius:6px;padding:8px;margin-bottom:8px;border:1px solid rgba(0,0,0,0.08);">
                    <div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:4px;">
                        <span>Arrive: <b style="color:${arrivePct < 20 ? '#ef4444' : arrivePct < 35 ? '#f97316' : 'inherit'}">${arrivePct}%</b></span>
                        <span>Depart: <b style="color:#10b981">${departPct}%</b></span>
                    </div>
                    <div style="height:6px;background:rgba(0,0,0,0.12);border-radius:3px;overflow:hidden;position:relative;">
                        <div style="position:absolute;height:100%;width:${departPct}%;background:#10b981;opacity:0.35;border-radius:3px;"></div>
                        <div style="position:absolute;height:100%;width:${arrivePct}%;background:#ef4444;border-radius:3px;"></div>
                    </div>
                </div>
                <div style="text-align:center;font-weight:700;font-size:0.85rem;color:#059669;margin-bottom:2px;">Buy ${stop.gallons_to_buy} gal @ $${stop.price_per_gallon}/gal</div>
                <div style="text-align:center;font-size:0.7rem;opacity:0.6;margin-bottom:8px;">${(stop.gallons_to_buy * 3.78541).toFixed(1)} L · total ${stop.cost_at_stop_display}</div>
                <div style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.2);border-radius:6px;padding:6px;font-size:0.7rem;color:#2563eb;">
                    💡 ${stop.decision_reason}
                </div>
            </div>`;

        const marker = L.marker([stop.lat, stop.lon], {
            icon: L.divIcon({ className: 'custom-div-icon', html: iconHtml, iconSize: [24, 24], iconAnchor: [12, 12] })
        }).bindPopup(popupContent).addTo(markerLayer);

        // Sidebar card (visible version)
        const div = document.createElement('div');
        div.className = 'group bg-slate-50 dark:bg-gray-900/40 hover:bg-white dark:hover:bg-gray-700 p-2.5 rounded-xl border border-slate-200 dark:border-gray-700 cursor-pointer transition-all duration-200 hover:shadow-sm';
        div.innerHTML = `
            <div class="flex justify-between items-center gap-2 mb-1.5">
                <div class="flex items-center gap-2 min-w-0 flex-1">
                    <div class="relative shrink-0">
                        <span class="bg-emerald-500 text-white w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold shadow-sm shadow-emerald-500/10">${stop.order}</span>
                        ${isCheapest ? '<span class="absolute -top-1.5 -right-1.5 text-[9px]">⭐</span>' : ''}
                    </div>
                    <div class="min-w-0">
                        <h4 class="font-bold text-slate-700 dark:text-gray-200 truncate text-[11.5px] leading-tight group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors">${stop.name}</h4>
                        <p class="text-[9px] text-slate-400 dark:text-gray-500 font-medium tracking-tight">Mile ${stop.miles_along_route} · ${stop.city}, ${stop.state}</p>
                    </div>
                </div>
                <div class="text-right shrink-0">
                    <span class="block text-emerald-600 dark:text-emerald-400 font-black text-xs">${stop.cost_at_stop_display}</span>
                </div>
            </div>
            
            <div class="flex items-center justify-between bg-white dark:bg-gray-800/40 rounded-lg px-2 py-1 border border-slate-100 dark:border-gray-700/30">
                <div class="flex items-center gap-3">
                    <div class="flex items-center gap-1.5">
                        <span class="text-[8px] text-slate-400 dark:text-gray-500 uppercase font-extrabold tracking-tighter">Buy</span>
                        <span class="text-[11px] font-bold text-slate-600 dark:text-gray-300">${stop.gallons_to_buy} <span class="text-[9px] font-normal opacity-50">gal</span></span>
                    </div>
                    <div class="w-px h-3 bg-slate-200 dark:bg-gray-700"></div>
                    <div class="flex items-center gap-1.5">
                        <span class="text-[8px] text-slate-400 dark:text-gray-500 uppercase font-extrabold tracking-tighter">Price</span>
                        <span class="text-[11px] font-bold text-emerald-600 dark:text-emerald-400">$${stop.price_per_gallon}</span>
                    </div>
                </div>
                
                <div class="flex items-center gap-1">
                    ${isDetour ? `
                        <div class="flex items-center gap-1 bg-orange-50 dark:bg-orange-900/20 px-1.5 py-0.5 rounded border border-orange-100/50 dark:border-orange-900/30">
                            <span class="text-[8px] font-bold text-orange-600 dark:text-orange-400">${stop.miles_from_route}mi detour</span>
                        </div>
                    ` : ''}
                </div>
            </div>`;

        div.onclick = () => { map.flyTo([stop.lat, stop.lon], 13); marker.openPopup(); };
        stopsList.appendChild(div);
    });

    if (activeData.fuel_stops.length === 0) {
        stopsList.innerHTML = `
            <div class="py-8 text-center">
                <div class="text-slate-400 dark:text-gray-500 mb-2">🏁</div>
                <p class="text-xs text-slate-500 dark:text-gray-400 font-medium">No fuel stops required for this route.</p>
            </div>`;
    }
}

function addMapMarker(coords, colorClass, title, subtitle) {
    L.marker(coords, {
        icon: L.divIcon({ className: 'custom-div-icon', html: `<div class="marker-pin ${colorClass}"></div>`, iconSize: [24, 24], iconAnchor: [12, 12] })
    }).bindPopup(`<strong>${title}</strong><br><span style="opacity:0.7">${subtitle}</span>`).addTo(markerLayer);
}

// ─────────────────────────────────────────
// Map legend (both routes)
// ─────────────────────────────────────────
let mapLegendControl = null;

function updateMapLegend() {
    if (mapLegendControl) mapLegendControl.remove();

    const fastestIsActive = currentStrategy === 'fastest';

    mapLegendControl = L.control({ position: 'bottomleft' });
    mapLegendControl.onAdd = () => {
        const div = L.DomUtil.create('div');
        div.innerHTML = `
            <div style="
                background: rgba(15,23,42,0.82);
                backdrop-filter: blur(8px);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 10px;
                padding: 8px 12px;
                font-family: Inter, sans-serif;
                font-size: 11px;
                color: #f1f5f9;
                min-width: 170px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            ">
                <div style="font-weight:700;font-size:10px;letter-spacing:0.08em;opacity:0.55;margin-bottom:7px;text-transform:uppercase;">Route Legend</div>

                <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;">
                    <div style="flex-shrink:0;display:flex;align-items:center;gap:3px;">
                        <div style="width:18px;height:3px;background:#10b981;border-radius:2px;${fastestIsActive ? 'background:repeating-linear-gradient(90deg,#10b981 0,#10b981 5px,transparent 5px,transparent 9px);opacity:0.7;' : ''}"></div>
                    </div>
                    <span style="font-weight:${fastestIsActive ? '400' : '700'};opacity:${fastestIsActive ? '0.7' : '1'};">
                        💰 Max Savings ${fastestIsActive ? '' : '<span style="background:#10b981;color:#fff;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:3px;">ACTIVE</span>'}
                    </span>
                </div>

                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="flex-shrink:0;display:flex;align-items:center;gap:3px;">
                        <div style="width:18px;height:3px;background:#fbbf24;border-radius:2px;${fastestIsActive ? '' : 'background:repeating-linear-gradient(90deg,#fbbf24 0,#fbbf24 5px,transparent 5px,transparent 9px);opacity:0.7;'}"></div>
                    </div>
                    <span style="font-weight:${fastestIsActive ? '700' : '400'};opacity:${fastestIsActive ? '1' : '0.7'};">
                        ⚡ Fastest Route ${fastestIsActive ? '<span style="background:#fbbf24;color:#1e293b;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:3px;">ACTIVE</span>' : ''}
                    </span>
                </div>

                <div style="margin-top:7px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-size:10px;opacity:0.45;">
                    ── solid = active &nbsp;·&nbsp; - - dashed = background
                </div>
            </div>`;
        return div;
    };
    mapLegendControl.addTo(map);
}

// ─────────────────────────────────────────
// Copy summary
// ─────────────────────────────────────────
document.getElementById('copyTripBtn').addEventListener('click', () => {
    const text = `Spotter Route Summary\nDistance: ${document.getElementById('sumMiles').textContent}\nTravel Time: ${document.getElementById('sumTime').textContent}\nFuel Cost: ${document.getElementById('sumCost').textContent}\nMoney Saved: ${document.getElementById('sumSaved').textContent}`;
    navigator.clipboard.writeText(text);
    const btn = document.getElementById('copyTripBtn');
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = orig, 2000);
});

// ─────────────────────────────────────────
// Theme toggle
// ─────────────────────────────────────────
document.getElementById('themeToggle').addEventListener('click', () => {
    document.documentElement.classList.toggle('dark');
    const isDark = document.documentElement.classList.contains('dark');
    document.getElementById('sunIcon').classList.toggle('hidden', !isDark);
    document.getElementById('moonIcon').classList.toggle('hidden', isDark);
    map.removeLayer(currentTileLayer);
    currentTileLayer = L.tileLayer(
        isDark ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
               : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        { attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }
    ).addTo(map);
});

// ─────────────────────────────────────────
// Autocomplete
// ─────────────────────────────────────────
function debounce(fn, wait) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}

async function fetchSuggestions(query) {
    if (!query || query.length < 3) return [];
    try {
        const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&addressdetails=1&limit=5&countrycodes=us`);
        return await res.json();
    } catch { return []; }
}

function setupAutocomplete(inputId, suggestionsId, isStart) {
    const input = document.getElementById(inputId);
    const box = document.getElementById(suggestionsId);

    input.addEventListener('input', debounce(async (e) => {
        if (isStart) startCoords = null; else endCoords = null;
        const results = await fetchSuggestions(e.target.value);
        if (results.length) {
            box.innerHTML = results.map(r => `
                <div class="suggestion-item" data-value="${r.display_name}" data-lat="${r.lat}" data-lon="${r.lon}">
                    <span class="city-name">${r.display_name.split(',')[0]}</span>
                    <span class="state-name">${r.display_name.split(',').slice(1, 3).join(',')}</span>
                </div>`).join('');
            box.classList.remove('hidden');
        } else {
            box.classList.add('hidden');
        }
    }, 400));

    box.addEventListener('click', (e) => {
        const item = e.target.closest('.suggestion-item');
        if (!item) return;
        input.value = item.dataset.value;
        const lat = parseFloat(item.dataset.lat), lon = parseFloat(item.dataset.lon);
        if (isStart) startCoords = [lon, lat]; else endCoords = [lon, lat];
        box.classList.add('hidden');
    });

    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !box.contains(e.target)) box.classList.add('hidden');
    });
}

setupAutocomplete('startInput', 'startSuggestions', true);
setupAutocomplete('endInput', 'endSuggestions', false);
