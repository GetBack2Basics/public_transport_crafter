/*
  src/Web/static/app.js
  Interactive client-side engine for NSW Public Transport Planning Portal.
  Handles AI clarification prompts, GCS DuckDB SQL generation,
  synchronized Leaflet map visualization, and full-day timetable recommendations.
*/

// Application State
const state = {
  route_a: "275",
  route_b: "CCN",
  interchange: "Morisset",
  min_buf: 5,
  max_buf: 15,
  agency_a: "2450",
  sql: "",
  map: null,
  mapLayers: {
    markers: null,
    isochrones: null
  }
};

// DOM Elements
const nlInput = document.getElementById("nlInput");
const btnAnalyze = document.getElementById("btnAnalyze");
const clarificationBox = document.getElementById("clarificationBox");
const clarificationQuestions = document.getElementById("clarificationQuestions");
const btnApplyClarification = document.getElementById("btnApplyClarification");

const sqlInput = document.getElementById("sqlInput");
const btnGenerateSql = document.getElementById("btnGenerateSql");
const btnRunQuery = document.getElementById("btnRunQuery");

const opalVolume = document.getElementById("opalVolume");
const opalSub = document.getElementById("opalSub");
const trafficVariance = document.getElementById("trafficVariance");
const trafficSub = document.getElementById("trafficSub");

const kpiTotalTrips = document.getElementById("kpiTotalTrips");
const kpiOptimalPct = document.getElementById("kpiOptimalPct");
const kpiPvr = document.getElementById("kpiPvr");
const kpiBuffer = document.getElementById("kpiBuffer");
const recTableBody = document.getElementById("recTableBody");

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  bindEvents();
  // Run initial default scenario
  analyzeQuery(nlInput.value);
});

// Initialize Leaflet Map
function initMap() {
  state.map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: false
  }).setView([-33.1118, 151.4883], 13);

  // Basemaps (Zero Carto tiles!)
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  });

  const esriSat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
    maxZoom: 18
  });

  osm.addTo(state.map);

  L.control.layers({
    "OpenStreetMap (Arterial)": osm,
    "Esri Satellite (High-Res)": esriSat
  }).addTo(state.map);

  state.mapLayers.markers = L.layerGroup().addTo(state.map);
  state.mapLayers.isochrones = L.layerGroup().addTo(state.map);
}

// Bind UI Events
function bindEvents() {
  btnAnalyze.addEventListener("click", () => analyzeQuery(nlInput.value));

  nlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeQuery(nlInput.value);
  });

  btnGenerateSql.addEventListener("click", () => generateSql());
  btnRunQuery.addEventListener("click", () => executeQuery());

  btnApplyClarification.addEventListener("click", () => {
    clarificationBox.style.display = "none";
    generateSql();
  });

  // Quick Chips
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      nlInput.value = chip.dataset.q;
      analyzeQuery(nlInput.value);
    });
  });
}

// Step 1: Analyze Intent & Handle Clarifications
async function analyzeQuery(queryText) {
  if (!queryText.trim()) return;

  btnAnalyze.innerHTML = '<span class="spinner"></span> Analyzing...';
  btnAnalyze.disabled = true;

  try {
    const res = await fetch("/api/analyze-intent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: queryText })
    });
    const data = await res.json();

    // Extract detected parameters
    if (data.detected_routes && data.detected_routes.length >= 2) {
      state.route_a = data.detected_routes[0];
      state.route_b = data.detected_routes[1];
    } else if (data.detected_routes && data.detected_routes.length === 1) {
      state.route_a = data.detected_routes[0];
      state.route_b = queryText.toLowerCase().includes("train") ? "CCN" : "270";
    }

    if (data.detected_stations && data.detected_stations.length > 0) {
      state.interchange = data.detected_stations[0];
    }

    if (data.transfer_window) {
      state.min_buf = data.transfer_window.min_minutes || 5;
      state.max_buf = data.transfer_window.max_minutes || 15;
    }

    if (data.detected_region === "hunter") {
      state.agency_a = "2450";
    }

    // Check if clarifications needed
    if (!data.is_complete && data.clarifications_needed.length > 0) {
      renderClarifications(data.clarifications_needed);
      clarificationBox.style.display = "flex";
    } else {
      clarificationBox.style.display = "none";
      await generateSql();
    }
  } catch (err) {
    console.error("Error analyzing intent:", err);
  } finally {
    btnAnalyze.innerHTML = "<span>Analyze Query</span>";
    btnAnalyze.disabled = false;
  }
}

// Render Clarification Options
function renderClarifications(questions) {
  clarificationQuestions.innerHTML = "";

  questions.forEach((q, qIdx) => {
    const qDiv = document.createElement("div");
    qDiv.className = "clarification-question";

    const label = document.createElement("span");
    label.className = "clarification-label";
    label.textContent = `${qIdx + 1}. ${q.question}`;
    qDiv.appendChild(label);

    const optsGroup = document.createElement("div");
    optsGroup.className = "options-group";

    q.options.forEach((opt, optIdx) => {
      const optBtn = document.createElement("button");
      optBtn.className = "option-btn";
      if (optIdx === 0) optBtn.classList.add("selected");
      optBtn.textContent = opt;

      optBtn.addEventListener("click", () => {
        optsGroup.querySelectorAll(".option-btn").forEach((b) => b.classList.remove("selected"));
        optBtn.classList.add("selected");

        // Update state based on option choice
        if (q.parameter === "route_agency") {
          state.agency_a = opt.includes("CDC Hunter") ? "2450" : "2514";
        } else if (q.parameter === "connecting_route") {
          state.route_b = opt.includes("CCN") ? "CCN" : opt.includes("270") ? "270" : "269";
        } else if (q.parameter === "interchange") {
          state.interchange = opt.includes("Morisset") ? "Morisset" : opt.includes("Fassifern") ? "Fassifern" : "Toronto";
        }
      });

      optsGroup.appendChild(optBtn);
    });

    qDiv.appendChild(optsGroup);
    clarificationQuestions.appendChild(qDiv);
  });
}

// Step 2: Generate SQL & Fetch Strategic Context
async function generateSql() {
  btnGenerateSql.innerHTML = '<span class="spinner"></span> Building...';
  btnGenerateSql.disabled = true;

  try {
    const res = await fetch("/api/generate-sql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        route_a: state.route_a,
        route_b: state.route_b,
        interchange: state.interchange,
        min_buffer: state.min_buf,
        max_buffer: state.max_buf,
        agency_a: state.agency_a
      })
    });
    const data = await res.json();

    state.sql = data.sql;
    sqlInput.value = data.sql;

    // Update Context Cards
    if (data.patronage) {
      opalVolume.textContent = `${data.patronage.total_monthly_trips.toLocaleString()} trips/mo`;
      opalSub.textContent = `${data.patronage.clean_station_name} (~${data.patronage.daily_avg_patronage.toLocaleString()} daily | Rank: #${data.patronage.statewide_rank})`;
    } else {
      opalVolume.textContent = "Interchange Loading";
      opalSub.textContent = "Multi-route connection hub";
    }

    if (data.congestion) {
      trafficVariance.textContent = `±${data.congestion.traffic_variance_min}m Variance`;
      trafficSub.textContent = `Road buffer +${data.buffer_adjustment}m applied (${data.effective_min_buffer}-${data.effective_max_buffer}m resilient window)`;
      kpiBuffer.textContent = `${data.effective_min_buffer} - ${data.effective_max_buffer} min`;
    } else {
      trafficVariance.textContent = "±2.0m Baseline Variance";
      trafficSub.textContent = `Standard transit transfer window (${data.effective_min_buffer}-${data.effective_max_buffer}m)`;
      kpiBuffer.textContent = `${data.effective_min_buffer} - ${data.effective_max_buffer} min`;
    }

    // Automatically trigger query execution
    await executeQuery();
  } catch (err) {
    console.error("Error generating SQL:", err);
  } finally {
    btnGenerateSql.innerHTML = "Regenerate SQL";
    btnGenerateSql.disabled = false;
  }
}

// Step 3 & 4: Execute on GCS & Display Recommendations
async function executeQuery() {
  const querySql = sqlInput.value.trim();
  if (!querySql) return;

  btnRunQuery.innerHTML = '<span class="spinner"></span> Running on GCS...';
  btnRunQuery.disabled = true;

  try {
    const res = await fetch("/api/execute-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sql: querySql,
        route_a: state.route_a,
        route_b: state.route_b,
        interchange: state.interchange,
        min_buffer: state.min_buf,
        max_buffer: state.max_buf
      })
    });
    const data = await res.json();

    if (data.status === "empty") {
      recTableBody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; color: var(--accent-amber); padding: 2rem;">
            ⚠️ No connecting service pairs found for '${state.interchange}'. Try broadening the station filter or selecting another interchange.
          </td>
        </tr>
      `;
      return;
    }

    // Update KPIs
    if (data.kpis) {
      kpiTotalTrips.textContent = data.kpis.total_trips;
      kpiOptimalPct.textContent = `${data.kpis.optimal_pct}%`;
      kpiPvr.textContent = `${data.kpis.fleet_pvr} Buses`;
    }

    // Update Map
    updateMap(data.map);

    // Update Recommendations Table
    renderRecommendationsTable(data.recommendations);
  } catch (err) {
    console.error("Error executing query:", err);
    recTableBody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; color: var(--accent-rose); padding: 2rem;">
          ❌ Error executing query on GCS: ${err.message}
        </td>
      </tr>
    `;
  } finally {
    btnRunQuery.innerHTML = "<span>Run GCS Query</span>";
    btnRunQuery.disabled = false;
  }
}

// Update Map with Centering, Markers, and Isochrone Rings
function updateMap(mapData) {
  if (!mapData || !state.map) return;

  state.mapLayers.markers.clearLayers();
  state.mapLayers.isochrones.clearLayers();

  const [lat, lon] = mapData.center;
  state.map.setView([lat, lon], 14);

  // Add Interchange Station Marker
  const stationIcon = L.divIcon({
    className: "custom-station-icon",
    html: `<div style="background: var(--accent-cyan); width: 18px; height: 18px; border-radius: 50%; border: 3px solid #fff; box-shadow: 0 0 10px rgba(0,229,255,0.8);"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9]
  });

  const marker = L.marker([lat, lon], { icon: stationIcon }).addTo(state.mapLayers.markers);
  marker.bindPopup(`<b>${state.interchange} Interchange</b><br>Multi-modal transfer coordination hub`).openPopup();

  // Add 5-minute (400m) and 10-minute (800m) pedestrian catchment rings
  L.circle([lat, lon], {
    radius: 400,
    color: "#00e5ff",
    fillColor: "#00e5ff",
    fillOpacity: 0.12,
    weight: 2,
    dashArray: "4, 6"
  }).addTo(state.mapLayers.isochrones).bindTooltip("5-minute Walk Catchment (400m)");

  L.circle([lat, lon], {
    radius: 800,
    color: "#6366f1",
    fillColor: "#6366f1",
    fillOpacity: 0.06,
    weight: 1.5,
    dashArray: "4, 6"
  }).addTo(state.mapLayers.isochrones).bindTooltip("10-minute Walk Catchment (800m)");

  // Add other stops if available
  if (mapData.stops) {
    mapData.stops.forEach((s) => {
      L.circleMarker([s.lat, s.lon], {
        radius: 6,
        color: "#10b981",
        fillColor: "#10b981",
        fillOpacity: 0.8,
        weight: 1.5
      }).addTo(state.mapLayers.markers).bindTooltip(s.name);
    });
  }
}

// Render Recommendations Table
function renderRecommendationsTable(recommendations) {
  if (!recommendations || recommendations.length === 0) {
    recTableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-dim); padding: 2rem;">No recommendations generated.</td></tr>`;
    return;
  }

  recTableBody.innerHTML = "";

  recommendations.forEach((row) => {
    const tr = document.createElement("tr");

    let statusClass = "optimal";
    if (row.status.includes("TIGHT")) statusClass = "tight";
    else if (row.status.includes("LONG")) statusClass = "long";

    tr.innerHTML = `
      <td><b>${row.interchange}</b></td>
      <td><code>${row.trip_id}</code></td>
      <td>${row.headsign || "Connecting Service"}</td>
      <td style="color: var(--text-muted);">${row.base_dep}</td>
      <td style="color: #fff; font-weight: 700;">${row.suggested_dep}</td>
      <td style="color: var(--accent-cyan); font-weight: 700;">${row.shift_min}</td>
      <td>${row.inbound_buffer}</td>
      <td>${row.outbound_buffer}</td>
      <td><span class="badge-tag ${statusClass}">${row.status}</span></td>
    `;
    recTableBody.appendChild(tr);
  });
}
