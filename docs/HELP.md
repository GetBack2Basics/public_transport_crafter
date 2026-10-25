# NSW Transit Spatial Crafter — Practical User Guide

Welcome to the **NSW Public Transport Crafter** user guide! 

> **💡 The Everyday Commuter Problem:**
> Have you ever hopped off a bus at a train station, only to watch your train pulling away right in front of you? That's the worst!
> 
> Imagine you live in an area with just one bus route. Every morning, your bus arrives at the train station **5 minutes after the all-stops train has already left**, so you're stuck waiting a whole hour on a cold platform for the next train!
> 
> What if the bus was scheduled to leave your neighborhood **8 minutes earlier**? You would step off the bus, walk onto the platform with a comfortable 3-minute buffer, hop straight onto the train, and save nearly an hour of waiting every single day. The bus company doesn't need to purchase another bus or hire an extra driver—we simply shift departure times so buses and trains connect seamlessly!

---

## Quick Navigation
1. [Practical Guide: Planning Portal](#1-practical-guide-planning-portal)
2. [Practical Guide: Data QA Hub & Route Explorer](#2-practical-guide-data-qa-hub--route-explorer)
3. [Practical Guide: Command-Line Interface (CLI) & Tests](#3-practical-guide-command-line-interface-cli--tests)
4. [Frequently Asked Questions (FAQ)](#4-frequently-asked-questions-faq)
5. [Behind the Scenes: System Architecture & Zero-Mock Defense](#5-behind-the-scenes-system-architecture--zero-mock-defense)
6. [Live Cloud Storage (GCS) Endpoints & Data Lakehouse](#6-live-cloud-storage-gcs-endpoints--data-lakehouse)

---

## 1. Practical Guide: Planning Portal

The Planning Portal is accessible at [https://storage.googleapis.com/nsw-transit-spatial-crafter/index.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/index.html).

### Step 1: Natural Language Transit Inquiry & Quick Chips

![Planning Portal Overview](screenshots/01_planning_portal_overview.png)
*Figure 1: Initial state of the Planning Portal with inquiry bar, quick scenario chips, and live lakehouse indicators.*

You don't need any technical coding skills! Just type what you want in plain English:
- *"How can we optimize route 99 to connect with the train?"*
- *"Connect Carnes Hill bus to Liverpool Interchange trains"*
- Or click any of the preset scenario chips: **Route 99 Corridor**, **Route 275 Corridor**, or **Carnes Hill to Liverpool**.

### Step 2: Route Disambiguation (When Routes Have Twins)

![Parameter Clarification Modal](screenshots/02_planning_portal_clarification.png)
*Figure 2: Clarification card when multiple operators run routes with the same number.*

In NSW, some route numbers are used in more than one town. For instance, **Route 99** runs under Busways Central Coast (Charlestown to Lake Haven) and also under Premier Illawarra (Helensburgh to Thirroul). When you search Route 99, the system simply asks which corridor you want to work on. Click your choice and confirm.

### Step 3: Parameterized SQL & Real Road Alignment

![SQL & Context Engine](screenshots/03_planning_portal_sql_context.png)
*Figure 3: DuckDB SQL targeting GCS Parquet tables with Opal passenger demand and traffic delay buffers.*

The system generates an exact DuckDB query against our Google Cloud Storage Parquet lakehouse:
```sql
SELECT stop_id, arrival_time, departure_time, trip_id 
FROM read_parquet('gs://nsw-transit-spatial-crafter/lake/nsw_stop_times.parquet')
WHERE route_short_name = '99'
```

### Step 4: Synchronized Spatial Corridor Map (1km Walkable Buffer)

![Synchronized Spatial Map](screenshots/04_planning_portal_spatial_map.png)
*Figure 4: Road-snapped transit route in cyan/gold with 1km multi-modal catchment boundary.*

The map snaps directly to the actual road network (no fake straight lines). The dotted green outline marks a **1-kilometer walking catchment** (about a 10-12 minute walk) and highlights all multi-modal interchange connections using official [Transport for NSW Mode Symbols, Pictograms, and Network Colours](https://opendata.transport.nsw.gov.au/data/dataset/transport-mode-symbols-and-pictograms):
- **[T] Train Stations** (Official Melon Yellow / Orange `#F99D1C` / PMS 137C Roundel — Sydney Trains & NSW TrainLink)
- **[M] Metro Stations** (Official Teal `#168388` / PMS 321 Roundel — Sydney Metro M1)
- **[B] Bus Interchanges** (Official Transport Blue `#00B5E2` Roundel — Metropolitan & Regional Buses)
- **[F] Ferry Wharves** (Official Manly Green `#00774B` / PMS 3415C Roundel — Sydney Ferries)
- **[L] Light Rail Stops** (Official Red `#E4002B` Roundel — Sydney Light Rail L1, L2, L3)
- **[C] Regional Coaches** (Official Purple `#732A82` / PMS 7657C Roundel — NSW TrainLink Regional Coaches)

### Step 5: Full-Day Bidirectional Timetable Adjustments

![Timetable Adjustments & Recommendations](screenshots/05_planning_portal_timetable_recommendations.png)
*Figure 5: Optimized schedule recommendations with departure shifts and transfer buffers.*

The solver analyzes every scheduled trip from early morning until midnight:
- **Suggested Shift ($\Delta t$):** Small tweaks (e.g., leaving 5 minutes later or 3 minutes earlier).
- **Target Buffer Window (7–17 min):** Enough time for passengers to walk between platforms comfortably without long waits.
- **Strict Budget Guarantee:** **0 Extra Buses Required.**

---

## 2. Practical Guide: Data QA Hub & Route Explorer

The Data QA Hub is hosted at [https://storage.googleapis.com/nsw-transit-spatial-crafter/data_qa.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/data_qa.html).

### Statewide Verification KPIs

![QA Hub Overview & KPIs](screenshots/06_qa_hub_overview_kpis.png)
*Figure 6: Data QA Hub executive overview verifying 10,266 routes, 171,277 stops, and 45 Parquet tables.*

- **Ingested Routes:** `10,266` statewide routes.
- **Verified Stops:** `171,277` physical stop locations.
- **Parquet Tables:** `45` cloud lakehouse tables.
- **Zero-Mock Compliance:** `100%` genuine government feeds.

### Tab 1: GeoLibre Spatial Map Inspector

![GeoLibre Spatial Map Inspector](screenshots/07_qa_hub_spatial_map_inspector.png)
*Figure 7: Map Inspector with Route 880 loaded, showing dual-symbology stops and attribute table dock.*

- **Official TfNSW Dual-Symbology:** Train [T] and Metro [M] hubs shine with high-contrast circular halos and official TfNSW brand colors (`#F99D1C` & `#168388`), while bus stops are styled in Transport Blue [B] (`#00B5E2`).
- **Table Dock:** View every stop along the line in sequence with its mode roundel. Click **🎯 Zoom** on any row to fly directly to that stop on the map.
- **Basemap Switcher:** Switch between OpenStreetMap Standard, Topo / Terrain, and Esri Satellite Imagery with a live opacity slider.

![Basemap Provider Popover](screenshots/08_qa_hub_basemap_selector.png)
*Figure 8: Basemap selector and real-time contrast opacity slider.*

### Tab 2: Searchable Route Explorer (10,266 Routes)

![Searchable Route Explorer](screenshots/09_qa_hub_route_explorer.png)
*Figure 9: Searchable route explorer filtered for Hornsby.*

Search any route number, suburb, or street name across Trains, Metro, Metropolitan Buses, Regional Coaches, and Ferries. Click **🗺️ Inspect on Map** to immediately view its spatial path.

### Tab 3: Automated Quality Gates (8 of 8 Passed)

![Automated Quality Gates](screenshots/11_qa_hub_quality_gates.png)
*Figure 10: 8 automated quality gates enforcing zero-mock compliance.*

Like pre-flight checks on an aircraft, these 8 automated gates assert:
1. **G1 - Whitelist:** Sourced only from `api.transport.nsw.gov.au`.
2. **G2 - Bounds:** Coordinates strictly within NSW bounds `[-37.5, 141.0]` to `[-28.1, 153.6]`.
3. **G3 - Tokens:** Valid Transport for NSW API authentication.
4. **G4 - Magic Bytes:** Every table starts and ends with binary `b'PAR1'`.
5. **G5 - Deep Payload:** No masked HTML error pages.
6. **G6 - Span Completeness:** Full daytime span coverage (`04:00` to `24:00`).
7. **G7 - Headway Preservation:** Prevents bus bunching.
8. **G8 - Zero Added Fleet:** Peak vehicle requirements $\le$ baseline fleet.

---

## 3. Practical Guide: Command-Line Interface (CLI) & Tests

### Run Natural Language Query Optimization
```bash
python -m src.Orchestration.query_orchestrator \
  --query "With the same number of buses and trains, how can the route from Maitland to Newcastle University be optimized?" \
  --clean-local
```

### Run Test Suite (31 Automated Tests)
```bash
.venv\Scripts\pytest -v
```

### Deploy Web Portals to Google Cloud Storage
```bash
python scripts/deploy_portal_to_gcs.py
```

---

## 4. Frequently Asked Questions (FAQ)

### Q: Why does this cost zero taxpayer dollars for new buses?
**A:** The mathematical solver enforces a hard constraint:
$$\sum \text{Vehicles}_{\text{optimized}} \le \sum \text{Vehicles}_{\text{baseline}}$$
Departure shifts ($\Delta t$) only rearrange trip start times by a few minutes; the total fleet size and driver duty hours remain identical.

### Q: Can I look up routes in regional NSW?
**A:** Yes! All 10,266 routes across Sydney, the Blue Mountains, Central Coast, Hunter, Illawarra, and Regional NSW are fully indexed.

### Q: Why does the system run with zero idle server costs?
**A:** The application runs completely client-side in your web browser using DuckDB SQL and static Google Cloud Storage hosting. When nobody is using it, compute cost is $0.00.

---

## 5. Behind the Scenes: System Architecture & Zero-Mock Defense

```mermaid
flowchart TD
    User([User Natural Language Query]) --> Step1[1. Transit Query Parser & Clarification]
    Step1 --> Step2[2. Parameterized DuckDB SQL & Context Engine]
    Step2 --> GCS[(GCS Parquet Lakehouse & Opal Patronage)]
    GCS --> Step3[3. Synchronized Spatial Corridor Map]
    Step3 --> Step4[4. Zero-Resource Timetable Solver]
    Step4 --> Step5[5. Full-Day Bidirectional Recommendations & KPIs]
    
    subgraph DataIntegrity [Zero-Mock Defense & QA]
        QA1[10,266 Route Catalog]
        QA2[8/8 Automated Quality Gates]
        QA3[PAR1 Magic Bytes Validation]
        QA4[NSW Spatial Envelope [-37.5, 141.0] to [-28.1, 153.6]]
    end
    
    Step2 -.-> DataIntegrity
```

### Zero-Mock Audit Certificate

![Zero-Mock Audit Certificate](screenshots/14_qa_hub_audit_certificate.png)
*Figure 11: Zero-Mock Data Integrity Certificate.*

- **0 Synthetic Arrays:** Prohibits `Math.random()`, dummy coordinate generators, or placeholder schedules.
- **AST Codebase Scanner:** Every script is parsed via an Abstract Syntax Tree (AST) scanner to ensure zero simulated mock data.
- **31 of 31 Unit & Integration Tests Passed:** Verified mathematical constraints and magic bytes.

### Official Transport for NSW Symbology & Brand Standards
The application strictly implements the design guidelines and assets provided by Transport for NSW:
- **Transport Mode Symbols and Pictograms**: Sourced from the official [TfNSW Open Data Dataset](https://opendata.transport.nsw.gov.au/data/dataset/transport-mode-symbols-and-pictograms), utilizing standard letter roundels (`T`, `M`, `B`, `F`, `L`, `C`) for all spatial map pins, legend items, and tabular inspector badges.
- **Transport Network Colour Chart (TNCC)**: Formatted directly from [TfNSW Developer Resources](https://opendata.transport.nsw.gov.au/developers/resources#TNCC):
  - **Train [T]**: `#F99D1C` (Melon Yellow / Orange, PMS 137C, Avery 91589A) / `#F6891F` (Regional Trains)
  - **Metro [M]**: `#168388` (Teal, CMYK 100/22/42/2, PMS 321)
  - **Bus [B]**: `#00B5E2` (Transport Blue, CMYK 100/17/9/0)
  - **Ferry [F]**: `#00774B` (Manly Green, CMYK 100/27/89/16, PMS 3415C)
  - **Light Rail [L]**: `#E4002B` (Red, CMYK 0/100/100/0)
  - **Coach [C]**: `#732A82` (Purple, CMYK 98/100/0/0, PMS 7657C)

---

## 6. Live Cloud Storage (GCS) Endpoints & Data Lakehouse

Hosted on Google Cloud Storage with global CDN distribution:

### Web Applications

| Application | GCS Public URL | Description |
| :--- | :--- | :--- |
| **Interactive User Guide** | [https://storage.googleapis.com/nsw-transit-spatial-crafter/help.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/help.html) | Practical manual with visual screen grabs and walkthroughs. |
| **NSW Transit Crafter (Planning Portal)** | [https://storage.googleapis.com/nsw-transit-spatial-crafter/index.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/index.html) | Natural language query, road maps, and timetable solver. |
| **Data QA & Quality Gates Hub** | [https://storage.googleapis.com/nsw-transit-spatial-crafter/data_qa.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/data_qa.html) | 10,266 routes explorer, 8 quality gates, and 45 Parquet tables. |
| **GeoLibre Spatial Map Inspector** | [https://storage.googleapis.com/nsw-transit-spatial-crafter/geolibre_qa_inspect.html](https://storage.googleapis.com/nsw-transit-spatial-crafter/geolibre_qa_inspect.html) | Standalone WebGL map viewer with layer and table dock controls. |

### Data Lakehouse Artifacts

| Artifact Name | GCS Object URI / Link | Verified Count / Size | Format |
| :--- | :--- | :--- | :--- |
| **Data QA Manifest** | [`gs://nsw-transit-spatial-crafter/lake/nsw_data_qa_manifest.json`](https://storage.googleapis.com/nsw-transit-spatial-crafter/lake/nsw_data_qa_manifest.json) | Complete statewide summary metadata | JSON |
| **Statewide Routes Catalog** | [`gs://nsw-transit-spatial-crafter/lake/nsw_routes_catalog.json`](https://storage.googleapis.com/nsw-transit-spatial-crafter/lake/nsw_routes_catalog.json) | **10,266** verified public transit routes | JSON |
| **Timetable Optimizations Matrix** | [`gs://nsw-transit-spatial-crafter/lake/nsw_timetable_optimizations.json`](https://storage.googleapis.com/nsw-transit-spatial-crafter/lake/nsw_timetable_optimizations.json) | Full-day bidirectional trip offset solutions | JSON |
| **Parquet Lakehouse Tables (45)** | `gs://nsw-transit-spatial-crafter/lake/*.parquet` | **5,908,991** stop times, **171,277** stops | Apache Parquet (`PAR1`) |

---
*NSW Public Transport Crafter — Engineering Reference & System Manual*  
*Last Updated: October 2026*
