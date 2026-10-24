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
