"""
tests/test_gcs_deployment.py
Validates that all tables, metadata, layers, and web application assets are on GCS:
- Statewide GTFS lakehouse Parquet tables (routes, stops, trips, stop_times, calendar)
- Strategic context layers (Opal patronage, traffic corridor congestion, interchange geometries)
- Catalog manifest and Web Portal assets (index.html, style.css, app.js)
- Verifies CORS and Cloud-Native accessibility
"""

import pytest
from pathlib import Path
import json


def test_gcs_lakehouse_parquet_tables_exist():
    from src.Ingestion.gcs_manager import list_gcs_files, get_active_gcs_bucket
    bucket = get_active_gcs_bucket()
    lake_files = list_gcs_files(prefix="lake/")

    expected_tables = [
        "lake/nsw_routes.parquet",
        "lake/nsw_stops.parquet",
        "lake/nsw_trips.parquet",
        "lake/nsw_stop_times.parquet",
        "lake/nsw_calendar.parquet",
        "lake/nsw_opal_station_patronage.parquet",
        "lake/nsw_corridor_congestion.parquet"
    ]
    for table in expected_tables:
        assert table in lake_files, f"Expected {table} on GCS bucket {bucket}"


def test_gcs_json_layers_exist():
    from src.Ingestion.gcs_manager import list_gcs_files, get_active_gcs_bucket
    bucket = get_active_gcs_bucket()
    lake_files = list_gcs_files(prefix="lake/")

    expected_json = [
        "lake/nsw_opal_station_patronage.json",
        "lake/nsw_corridor_congestion.json",
        "lake/nsw_interchanges.json"
    ]
    for jf in expected_json:
        assert jf in lake_files, f"Expected {jf} on GCS bucket {bucket}"


def test_gcs_web_portal_and_catalog_manifest_exist():
    from src.Ingestion.gcs_manager import list_gcs_files, get_active_gcs_bucket
    bucket = get_active_gcs_bucket()
    all_files = list_gcs_files()

    assert "index.html" in all_files
    assert "app.js" in all_files
    assert "style.css" in all_files
    assert "catalog_manifest.json" in all_files or "config/catalog_manifest.json" in all_files


def test_gcs_cors_configuration():
    cors_file = Path("config/gcs_cors.json")
    assert cors_file.exists(), "config/gcs_cors.json must exist"
    with open(cors_file, "r", encoding="utf-8") as f:
        cors_config = json.load(f)
    assert len(cors_config) > 0
    rule = cors_config[0]
    assert "*" in rule.get("origin", [])
    assert "GET" in rule.get("method", [])
    assert "OPTIONS" in rule.get("method", [])


def test_gcs_data_qa_hub_and_manifest_exist():
    from src.Ingestion.gcs_manager import list_gcs_files, get_active_gcs_bucket
    bucket = get_active_gcs_bucket()
    all_files = list_gcs_files()

    assert "data_qa.html" in all_files, f"Expected data_qa.html on GCS bucket {bucket}"
    assert "data_qa.js" in all_files or "static/data_qa.js" in all_files, f"Expected data_qa.js on GCS bucket {bucket}"
    assert "lake/nsw_data_qa_manifest.json" in all_files, f"Expected lake/nsw_data_qa_manifest.json on GCS"
    assert "lake/nsw_routes_catalog.json" in all_files, f"Expected lake/nsw_routes_catalog.json on GCS"


def test_data_qa_manifest_contract_and_route_99():
    manifest_path = Path("data/lake/nsw_data_qa_manifest.json")
    assert manifest_path.exists(), "nsw_data_qa_manifest.json must exist locally"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    kpis = manifest.get("overall_kpis", {})
    assert kpis.get("total_routes") >= 10000, "Must catalog over 10,000 routes"
    assert kpis.get("total_stops") >= 150000, "Must catalog over 150,000 stops"
    assert kpis.get("total_trips") >= 200000, "Must catalog over 200,000 trips"
    assert kpis.get("zero_mock_certified") is True, "Must be Zero Mock Certified"
    assert len(manifest.get("quality_gates", [])) == 8, "Must verify 8 Quality Gates"

    # Verify Route 99 in routes catalog
    catalog_path = Path("data/lake/nsw_routes_catalog.json")
    assert catalog_path.exists(), "nsw_routes_catalog.json must exist locally"
    with open(catalog_path, "r", encoding="utf-8") as f:
        routes = json.load(f)

    route_99_entries = [r for r in routes if r.get("route_short_name") == "99"]
    assert len(route_99_entries) >= 2, f"Expected at least 2 Route 99 entries (Premier Illawarra & Busways), found {len(route_99_entries)}"
    
    agencies = {r.get("agency_id") for r in route_99_entries}
    assert "2455" in agencies, "Must include Premier Illawarra Route 99 (agency 2455)"
    assert "2606" in agencies, "Must include Busways Central Coast Route 99 (agency 2606)"

    # Verify Route 99 in optimizations
    opt_path = Path("data/lake/nsw_timetable_optimizations.json")
    assert opt_path.exists()
    with open(opt_path, "r", encoding="utf-8") as f:
        opts = json.load(f)

    assert "99_premier_illawarra_helensburgh" in opts, "Must include Route 99 Helensburgh Station optimization"
    h_opt = opts["99_premier_illawarra_helensburgh"]
    assert len(h_opt["recommendations"]) > 0, "Must have real trip recommendations for Route 99"
    assert len(h_opt["map"]["route_geometry"]) > 500, "Route 99 must have high-res road snapped geometry"

