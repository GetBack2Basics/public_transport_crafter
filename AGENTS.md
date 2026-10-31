# Project Memory & Architecture Directives: NSW Public Transport Crafter

## Core Rule: 100% GCS Cloud Lakehouse Processing

> **MANDATORY INVARIANT FOR ALL PROMPTS & RUNTIMES:**
> **All data processing, analytics, querying, pipeline execution, and dataset storage must be done on Google Cloud Storage (GCS).**
> **The local workspace is strictly reserved for code and documents.**

---

### Architectural Principles

1. **Local Scope: Code & Documents Only**
   - The local repository environment is strictly for:
     - Source code (`src/`, `scripts/`, `tests/`)
     - Documentation (`docs/`, `*.md`, specifications, RFCs)
     - Configuration files (`catalog_manifest.json`, environment definitions)
     - Lightweight test runners and unit test assertions.
   - No heavy production transit tables, bulk datasets, or large ETL dumps may be generated or processed as primary storage on local disk.

2. **GCS Cloud Lakehouse: Authoritative Processing Target**
   - All spatial, SQL, and timetable queries must target the GCS cloud lakehouse:
     `gs://nsw-transit-spatial-crafter/lake/` (or via HTTP endpoint `https://storage.googleapis.com/nsw-transit-spatial-crafter/lake/`).
   - Query engines (DuckDB, AlaSQL, server API, and client frontend) must execute against remote GCS Parquet tables (`read_parquet('gs://nsw-transit-spatial-crafter/lake/nsw_*.parquet')`).
   - Any pipeline updates, optimization matrices, spatial shape generations, and public assets must be published and persisted directly to the active GCS bucket.

3. **Physical Infrastructure Alignment Guarantee**
   - All bus routes must follow genuine road network centerlines.
   - All train routes must follow physical railway line tracks.
   - Zero synthetic point-to-point lines or linear offsets permitted.

