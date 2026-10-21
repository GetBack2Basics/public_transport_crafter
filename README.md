# NSW Transit Spatial Crafter (nsw_transit_spatial_crafter)

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Architecture: FunGIS MapInABox](https://img.shields.io/badge/Architecture-FunGIS%20MapInABox-emerald.svg)](https://github.com/GetBack2Basics/FunGIS_SpatialOlympics26_MapInABox)
[![Cloud: GCP Antigravity](https://img.shields.io/badge/Compute-GCP%20Antigravity%20($0.00%20Idle)-cyan.svg)](https://github.com/GetBack2Basics/CheatSheets/blob/main/gcp_antigravity_playbook.md)
[![Defense: AI Anti-Mock 3-Tier](https://img.shields.io/badge/Verification-3--Tier%20Anti--Mock-rose.svg)](https://github.com/GetBack2Basics/CheatSheets/blob/main/ai_anti_mock_hallucination_playbook.md)

Autonomous, query-driven transit analytics and zero-resource timetable optimization engine for New South Wales (TfNSW).

Forked and refactored from `hunter_spatial_crafter`, this engine **eliminates static pre-configured corridors**. Given any natural language transit query (e.g., *"With the same number of buses and trains, how can the route from Maitland to Newcastle University be optimized?"*), the system dynamically resolves transit subgraphs, checks local Parquet lakes or triggers just-in-time (JIT) ingestion from TfNSW Open Data, calculates walking isochrones, executes zero-resource fleet optimization, and outputs a standalone, offline-first **FunGIS Map-in-a-Box** HTML report with embedded client-side **AlaSQL**.

---

## 1. System Architecture: Just-In-Time (JIT) Query Pipeline

```
+-----------------------------------------------------------------------------------+
| 1. Query Orchestrator (src/Orchestration/query_orchestrator.py)                   |
|    - Parses Origin, Destination, Modes, Constraints ("fixed resources")           |
|    - Geocodes locations & identifies candidate transit lines / interchange hubs   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. Data Catalog & JIT Ingestion Router (src/Ingestion/catalog_router.py)          |
|    - Checks local Parquet lake & GCS bucket for required route/stop/Opal slices   |
|    - If MISSING: Dynamically builds config JSON & triggers data_importer.py       |
|    - Authenticates to TfNSW Open Data, downloads GTFS/Opal, verifies via 3-Tier   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. Dynamic Corridor Subgraph Extractor (src/Routing/corridor_extractor.py)        |
|    - Slices GTFS timetable & shapes into a targeted Multi-Modal Transfer Graph    |
|    - Calls Ephemeral Valhalla (GCP Antigravity) for walking transfer isochrones   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 4. Generalized Timetable & Resource Optimizer (src/Analysis/optimizer.py)         |
|    - Enforces Fixed Resource Constraints (Sum of active vehicles & hours <= base) |
|    - Shifts departure offsets (delta_t) to minimize transfer friction (4-8m goal) |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 5. FunGIS Map-in-a-Box Compiler (runner/build_transit_report.py)                  |
|    - Injects baseline vs optimized trips into standalone HTML deliverable         |
|    - Enables in-browser AlaSQL / DuckDB-WASM natural language SQL exploration     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Core Pillars & Playbook Compliance

### A. FunGIS Map-in-a-Box Pattern
- **Self-Contained & Offline-First**: Zero running backend required. The output `transit_insight_report.html` can be opened directly via `file:///` in any modern web browser or served from Google Cloud Storage static hosting.
- **`{{PLACEHOLDER}}` Compilation**: Pre-calculated matrices, GeoJSON layers, and schedule diffs are compiled into clean JavaScript objects without server runtime overhead.
- **Embedded AlaSQL Engine**: Enables natural language SQL queries directly in the client browser (e.g., *"Show transfers with wait time > 10 min"* $\to$ `SELECT * FROM transfers WHERE wait_time_minutes > 10`).

### B. Cloud-First GCS Processing & Review ($0.00 Idle Compute)
- **Local Is Strictly Code**: The local filesystem contains only source code, configs, templates, and tests. All data artifacts (`data/`) are ephemeral and git-ignored.
- **GCS Cloud Lakehouse**: Parquet datasets (GTFS slices, transit lines, Opal matrices) are staged in Google Cloud Storage (`gs://nsw-transit-spatial-crafter/lake/`).
- **Processing on GCS**: Valhalla pedestrian catchments (`gs://nsw-transit-spatial-crafter/isochrones/`) are computed via ephemeral spot compute workers (`e2-custom-2-9216`) with dynamic NAT IP discovery and immediate VM termination.
- **Review on GCS**: Compiled FunGIS Map-in-a-Box interactive HTML deliverables are automatically deployed to Google Cloud Storage with `Cache-Control: public, max-age=60` for instant global stakeholder review:
  `https://storage.googleapis.com/nsw-transit-spatial-crafter/transit_insight_report.html`

### C. Mandatory 3-Tier Anti-Mock Defense Model
- **Tier 1 (Pre-Execution Contract Assertion)**: Asserts endpoint legitimacy (`https://api.transport.nsw.gov.au/`), API token presence, and strict configuration schema before any network call.
- **Tier 3 (Deep Response Inspection)**: Asserts `HTTP 200`, valid MIME `Content-Type` (no masked HTML error pages or SSO challenges), and inspects JSON bodies for embedded error codes.
- **Tier 2 (Physical Artifact & Magic Bytes Assertion)**: Enforces physical file non-emptiness on disk, byte threshold checks (>4096 bytes), and asserts the binary Parquet header `b'PAR1'` and footer `b'PAR1'`.
- **Zero Mock Policy**: Prohibits random coordinates, dummy arrays, and synthetic timetables.

---

## 3. Mathematical Optimization Formulation (Zero-Resource Solver)

For any dynamically selected corridor under fixed resource constraints:

### Decision Variables
- $\Delta t_i \in [-\Delta_{\max}, +\Delta_{\max}]$: Integer departure offset (in minutes) for each scheduled feeder trip $i$ ($\Delta_{\max} = \pm 15$ minutes).

### Hard Constraints (Zero Added Budget)
1. **Fleet Limit (PVR)**:
   $$\sum \text{Vehicles}_{\text{optimized}} \le \sum \text{Vehicles}_{\text{baseline}}$$
   The Peak Vehicle Requirement (maximum concurrent buses active on the network) cannot exceed the existing fleet.
2. **Duty Hours / Fleet Invariant**:
   $$\text{CycleTime}(r) = \text{RunTime}(r) + \text{Layover}(r) \le \text{CycleTime}_{\text{scheduled}}(r)$$
   Total vehicle operating hours and driver shift duty hours remain invariant.
3. **Headway Regularity (Anti-Bunching)**:
   $$\text{Departure}_{i+1} - \text{Departure}_i \ge H_{\min}$$
   Maintains a minimum headway buffer between successive departures to prevent bus bunching.

### Objective Function (Minimize Transfer Friction)
$$\min_{\Delta t} \sum_{j \in \text{Transfers}} w_j \cdot \text{Penalty}(t_{\text{wait}, j})$$

Where $w_j$ is the passenger volume weight from Opal loadings, and the transfer friction penalty is:
$$
\text{Penalty}(t) = \begin{cases}
0, & \text{if } 4 \le t \le 8 \text{ min (Optimal Sweet Spot)} \\
(t - 8)^2, & \text{if } t > 8 \text{ min (Excessive Wait)} \\
10000 + 100 \cdot (4 - t), & \text{if } t < 4 \text{ min (Missed Connection Risk)}
\end{cases}
$$

---

## 4. Directory Layout

```
nsw_transit_spatial_crafter/
├── config/
│   ├── catalog_manifest.json          # Registry of all NSW GTFS & Opal datasets
│   └── templates/
│       └── dynamic_source_template.json # Template for JIT config generation
├── src/
│   ├── Ingestion/
│   │   ├── data_importer.py           # SINGLE reusable, config-driven importer
│   │   └── catalog_router.py          # Checks local/GCS cache & triggers JIT ingest
│   ├── Routing/
│   │   ├── corridor_extractor.py      # Dynamic origin-destination graph extractor
│   │   └── valhalla_client.py         # Ephemeral Valhalla API client
│   ├── Analysis/
│   │   ├── optimizer.py               # Generalized zero-resource timetable solver
│   │   └── transfer_friction_model.py # Evaluates connection buffers & Opal loadings
│   └── Orchestration/
│       └── query_orchestrator.py      # Entrypoint: NL query -> JIT fetch -> Solve -> Report
├── runner/
│   ├── build_transit_report.py        # Map-in-a-Box HTML compiler
│   └── templates/
│       └── map_in_a_box.html          # Template with AlaSQL & NL-to-SQL interface
├── scripts/
│   ├── run_ephemeral_valhalla.sh      # Antigravity VM lifecycle & routing script
│   └── sync_to_gcs.sh                 # Cloud Storage sync with cache-control
├── tests/
│   ├── test_data_importer.py          # Anti-mock & ingestion verification tests
│   ├── test_optimizer.py              # Zero-resource constraint validation tests
│   └── lint/
│       └── test_no_mock_data.py       # AST scanner from Anti-Mock Playbook
├── requirements.txt
└── README.md
```

---

## 5. Quickstart & CLI Execution

### 1. Environment Setup
```bash
# Clone and enter directory
cd c:/Projects/nsw_public_transport_crafter

# Activate virtual environment
.venv/Scripts/activate

# (Optional) Add your TfNSW Open Data API Key to .env
echo "TFNSW_API_KEY=your_tfnsw_api_token" > .env
```

### 2. Run Autonomous Query Orchestration
Execute any natural language transit query:

```bash
# Maitland to Newcastle University Corridor Optimization (Sync to GCS + Clean Local)
python -m src.Orchestration.query_orchestrator \
  --query "With the same number of buses and trains, how can the route from Maitland to Newcastle University be optimized?" \
  --clean-local

# Gosford to Hornsby Morning Peak Transfer Optimization
python -m src.Orchestration.query_orchestrator \
  --query "With no additional rolling stock, improve morning peak transfers from Gosford to Hornsby" \
  --clean-local
```

### 3. Review Deliverables on GCS (Zero Running Server)
All reviews are hosted directly on Google Cloud Storage with instant global CDN distribution:
* **Live Report Review**:
  [https://storage.googleapis.com/nsw-transit-spatial-crafter/transit_insight_report.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/transit_insight_report.html)
* **Archived Run Review**:
  `https://storage.googleapis.com/nsw-transit-spatial-crafter/reports/transit_insight_report.html`

---

## 6. Running Test Suites

Execute all Anti-Mock and Optimization constraint verification tests:
```bash
pytest tests/ -v
```

Tests include:
- `tests/lint/test_no_mock_data.py`: Zero-mock AST scanner asserting absence of synthetic arrays.
- `tests/test_data_importer.py`: Validates Tier 1 contract rejection, Tier 2 `b'PAR1'` magic bytes, and Tier 3 masked HTML rejection.
- `tests/test_optimizer.py`: Asserts hard constraints ($\sum \text{Vehicles}_{\text{opt}} \le \sum \text{Vehicles}_{\text{base}}$), headway preservation, and wait time reduction.
- `tests/test_extended_transit_catalog.py`: Asserts authoritative schema, Tier 2 magic bytes, and dynamic corridor routing across Regional Coaches, Sydney Metro M1, Greater Sydney B-Line, Blue Mountains, and Illawarra feeds.
- `tests/test_street_and_traffic_pipeline.py`: Validates road network & live traffic delay variance injection, zero Carto compliance, and independent GCS bucket configuration.
