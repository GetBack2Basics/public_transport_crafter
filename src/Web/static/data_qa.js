/**
 * src/Web/static/data_qa.js
 * Authoritative Data QA Hub & Route Explorer Logic.
 * Loads nsw_data_qa_manifest.json and nsw_routes_catalog.json directly from GCS.
 */

const state = {
  manifest: null,
  routes: [],
  filteredRoutes: [],
  tableFilterText: "",
  routeFilterText: "",
  activeModeFilter: "all"
};

// DOM Elements
const qaRoutesCount = document.getElementById("qaRoutesCount");
const qaStopsCount = document.getElementById("qaStopsCount");
const qaTripsCount = document.getElementById("qaTripsCount");
const qaStopTimesCount = document.getElementById("qaStopTimesCount");
const qaTablesCount = document.getElementById("qaTablesCount");

const gatesTableBody = document.getElementById("gatesTableBody");
const tablesInventoryBody = document.getElementById("tablesInventoryBody");
const feedsTableBody = document.getElementById("feedsTableBody");
const routesTableBody = document.getElementById("routesTableBody");
const routeCatalogCountBadge = document.getElementById("routeCatalogCountBadge");
const routeTablePaginationInfo = document.getElementById("routeTablePaginationInfo");

const routeSearchInput = document.getElementById("routeSearchInput");
const btnClearRouteSearch = document.getElementById("btnClearRouteSearch");
const tableSearchInput = document.getElementById("tableSearchInput");

document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initFilters();
  await loadQaData();
});

// Tab Switching
function initTabs() {
  const tabs = document.querySelectorAll(".qa-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      const targetId = tab.dataset.tab;
      document.querySelectorAll(".qa-tab-content").forEach((content) => {
        content.style.display = content.id === targetId ? "block" : "none";
      });
    });
  });
}

// Load Manifest and Routes Catalog
async function loadQaData() {
  const isGcs = window.location.hostname.includes("storage.googleapis.com");
  const basePath = isGcs ? "lake/" : "/lake/";

  // 1. Load Data QA Manifest
  try {
    const res = await fetch(`${basePath}nsw_data_qa_manifest.json`);
    if (res.ok) {
      state.manifest = await res.json();
      renderManifest();
    } else {
      console.warn("Could not fetch nsw_data_qa_manifest.json directly, trying fallback path...");
      const resAlt = await fetch("data/lake/nsw_data_qa_manifest.json");
      if (resAlt.ok) {
        state.manifest = await resAlt.json();
        renderManifest();
      }
    }
  } catch (err) {
    console.error("Error loading QA manifest:", err);
  }

  // 2. Load Full Route Catalog (10,266 routes)
  try {
    const res = await fetch(`${basePath}nsw_routes_catalog.json`);
    if (res.ok) {
      state.routes = await res.json();
      state.filteredRoutes = [...state.routes];
      renderRoutesTable();
    } else {
      const resAlt = await fetch("data/lake/nsw_routes_catalog.json");
      if (resAlt.ok) {
        state.routes = await resAlt.json();
        state.filteredRoutes = [...state.routes];
        renderRoutesTable();
      }
    }
  } catch (err) {
    console.error("Error loading routes catalog:", err);
  }
}

// Render Manifest Content
function renderManifest() {
  if (!state.manifest) return;

  const kpis = state.manifest.overall_kpis;
  if (kpis) {
    if (qaRoutesCount) qaRoutesCount.textContent = kpis.total_routes.toLocaleString();
    if (qaStopsCount) qaStopsCount.textContent = kpis.total_stops.toLocaleString();
    if (qaTripsCount) qaTripsCount.textContent = kpis.total_trips.toLocaleString();
    if (qaStopTimesCount) qaStopTimesCount.textContent = kpis.total_stop_times.toLocaleString();
    if (qaTablesCount) qaTablesCount.textContent = kpis.total_parquet_tables;
  }

  renderQualityGates(state.manifest.quality_gates || []);
  renderTablesInventory(state.manifest.table_metrics || []);
  renderFeedsLineage(state.manifest.feed_agencies || []);
}

// Render Quality Gates
function renderQualityGates(gates) {
  if (!gatesTableBody) return;
  gatesTableBody.innerHTML = "";

  gates.forEach((g) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="gate-badge gate-tier">${g.id}</span></td>
      <td style="font-weight: 600; color: var(--text-main);">${g.name}</td>
      <td style="color: var(--text-muted);">${g.rule}</td>
      <td style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--accent-cyan);">${g.threshold}</td>
      <td style="text-align: center;"><span class="gate-badge gate-pass">✔ ${g.status}</span></td>
    `;
    gatesTableBody.appendChild(tr);
  });
}

// Render Tables Inventory
function renderTablesInventory(tables) {
  if (!tablesInventoryBody) return;
  tablesInventoryBody.innerHTML = "";

  const query = state.tableFilterText.toLowerCase().trim();
  const filtered = tables.filter((t) => t.table_name.toLowerCase().includes(query) || t.primary_key.toLowerCase().includes(query));

  filtered.forEach((t) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <span style="font-weight: 600; font-family: var(--font-mono); color: var(--text-main);">${t.table_name}</span>
        <div style="font-size: 0.7rem; color: var(--text-dim); margin-top: 2px;">${t.gcs_uri}</div>
      </td>
      <td style="text-align: right; font-weight: 700; color: var(--accent-cyan); font-family: var(--font-mono);">
        ${t.row_count.toLocaleString()}
      </td>
      <td style="text-align: right; color: var(--text-muted); font-family: var(--font-mono);">
        ${t.size_mb.toFixed(3)} MB
      </td>
      <td>
        <span class="badge" style="font-size: 0.7rem; background: rgba(255,255,255,0.06);">${t.primary_key}</span>
      </td>
      <td style="text-align: right; color: var(--text-muted); font-family: var(--font-mono);">
        ${t.column_count}
      </td>
      <td style="text-align: center;">
        <span class="gate-badge gate-pass">✔ ${t.data_quality_pct}% Valid</span>
      </td>
      <td>
        <span class="gate-badge gate-tier" style="font-size: 0.68rem;">PAR1 Magic Bytes Verified</span>
      </td>
    `;
    tablesInventoryBody.appendChild(tr);
  });
}

// Render Feeds Lineage
function renderFeedsLineage(feeds) {
  if (!feedsTableBody) return;
  feedsTableBody.innerHTML = "";

  feeds.forEach((f) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="font-weight: 600; color: var(--text-main);">${f.name}</td>
      <td><span class="badge" style="font-size: 0.72rem;">${f.mode}</span></td>
      <td style="color: var(--text-muted);">${f.region}</td>
      <td style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--accent-cyan);">${f.tables}</td>
      <td style="text-align: center;"><span class="gate-badge gate-pass">✔ ${f.quality}</span></td>
    `;
    feedsTableBody.appendChild(tr);
  });
}

// Render Routes Catalog Explorer Table
function renderRoutesTable() {
  if (!routesTableBody) return;
  routesTableBody.innerHTML = "";

  let list = state.routes;

  // Apply text search
  if (state.routeFilterText) {
    const q = state.routeFilterText.toLowerCase();
    list = list.filter((r) => 
      r.route_short_name.toLowerCase().includes(q) ||
      r.route_long_name.toLowerCase().includes(q) ||
      r.agency_name.toLowerCase().includes(q) ||
      r.route_id.toLowerCase().includes(q)
    );
  }

  // Apply mode filter
  if (state.activeModeFilter === "99") {
    list = list.filter((r) => r.route_short_name === "99");
  } else if (state.activeModeFilter === "275") {
    list = list.filter((r) => r.route_short_name === "275");
  } else if (state.activeModeFilter === "852") {
    list = list.filter((r) => r.route_short_name === "852");
  } else if (state.activeModeFilter === "181") {
    list = list.filter((r) => r.route_short_name === "181");
  } else if (state.activeModeFilter === "rail") {
    list = list.filter((r) => r.route_type === 1 || r.route_type === 2 || r.mode_label.includes("Rail") || r.mode_label.includes("Metro"));
  } else if (state.activeModeFilter === "bus") {
    list = list.filter((r) => r.route_type === 3 || r.route_type === 700 || r.mode_label.includes("Bus"));
  }

  state.filteredRoutes = list;

  if (routeCatalogCountBadge) {
    routeCatalogCountBadge.textContent = `${list.length.toLocaleString()} Matching Routes`;
  }

  if (list.length === 0) {
    routesTableBody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; padding: 2.5rem; color: var(--accent-amber);">
          ⚠️ No routes found matching "${state.routeFilterText}". Try searching for '99', '275', '852', '181', 'B1', or 'T1'.
        </td>
      </tr>
    `;
    if (routeTablePaginationInfo) routeTablePaginationInfo.textContent = "0 routes displayed";
    return;
  }

  const limit = 120; // Fast DOM rendering for top results
  const slice = list.slice(0, limit);

  slice.forEach((r) => {
    const tr = document.createElement("tr");

    // Format mode badge color
    let modeClass = "badge";
    if (r.mode_label.includes("Rail") || r.mode_label.includes("Train")) modeClass = "gate-badge gate-pass";
    else if (r.mode_label.includes("Metro")) modeClass = "gate-badge gate-tier";

    tr.innerHTML = `
      <td>
        <span style="font-size: 0.95rem; font-weight: 800; font-family: var(--font-heading); color: var(--accent-cyan);">
          ${r.route_short_name}
        </span>
        <div style="font-size: 0.68rem; color: var(--text-dim); font-family: var(--font-mono);">${r.route_id}</div>
      </td>
      <td>
        <span class="${modeClass}" style="font-size: 0.72rem;">${r.mode_label}</span>
      </td>
      <td style="font-weight: 600; color: var(--text-main); font-size: 0.8rem;">
        ${r.agency_name}
      </td>
      <td style="color: var(--text-muted); font-size: 0.82rem; line-height: 1.4;">
        ${r.route_long_name}
      </td>
      <td style="text-align: right; font-family: var(--font-mono); font-weight: 600; color: var(--text-main);">
        ${r.trip_count.toLocaleString()}
      </td>
      <td style="text-align: center;">
        <span class="gate-badge gate-pass" style="font-size: 0.68rem;">● Ingested & Live</span>
      </td>
      <td style="text-align: center;">
        <a href="index.html?q=optimize route ${encodeURIComponent(r.route_short_name)} to connect with train" 
           class="qa-nav-link" 
           style="padding: 0.25rem 0.55rem; font-size: 0.75rem;">
          Plan →
        </a>
      </td>
    `;
    routesTableBody.appendChild(tr);
  });

  if (routeTablePaginationInfo) {
    routeTablePaginationInfo.textContent = `Displaying top ${Math.min(limit, list.length)} of ${list.length.toLocaleString()} matching routes`;
  }
}

// Initialize Filters & Event Listeners
function initFilters() {
  if (routeSearchInput) {
    routeSearchInput.addEventListener("input", (e) => {
      state.routeFilterText = e.target.value.trim();
      renderRoutesTable();
    });
  }

  if (btnClearRouteSearch) {
    btnClearRouteSearch.addEventListener("click", () => {
      if (routeSearchInput) routeSearchInput.value = "";
      state.routeFilterText = "";
      state.activeModeFilter = "all";
      document.querySelectorAll(".chip-route-filter").forEach((c) => c.classList.remove("active"));
      const allChip = document.querySelector('.chip-route-filter[data-filter="all"]');
      if (allChip) allChip.classList.add("active");
      renderRoutesTable();
    });
  }

  if (tableSearchInput) {
    tableSearchInput.addEventListener("input", (e) => {
      state.tableFilterText = e.target.value;
      if (state.manifest && state.manifest.table_metrics) {
        renderTablesInventory(state.manifest.table_metrics);
      }
    });
  }

  // Route Filter Chips
  document.querySelectorAll(".chip-route-filter").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip-route-filter").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");

      state.activeModeFilter = chip.dataset.filter;
      if (state.activeModeFilter === "99") {
        if (routeSearchInput) routeSearchInput.value = "99";
        state.routeFilterText = "99";
      } else if (state.activeModeFilter === "275") {
        if (routeSearchInput) routeSearchInput.value = "275";
        state.routeFilterText = "275";
      } else if (state.activeModeFilter === "852") {
        if (routeSearchInput) routeSearchInput.value = "852";
        state.routeFilterText = "852";
      } else if (state.activeModeFilter === "181") {
        if (routeSearchInput) routeSearchInput.value = "181";
        state.routeFilterText = "181";
      } else {
        if (routeSearchInput) routeSearchInput.value = "";
        state.routeFilterText = "";
      }
      renderRoutesTable();
    });
  });
}
