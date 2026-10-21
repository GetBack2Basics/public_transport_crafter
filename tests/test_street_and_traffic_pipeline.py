"""
tests/test_street_and_traffic_pipeline.py
Validates Street Network & Live Traffic Data ingestion,
mapping layer compliance (OSM and Esri ONLY - zero Carto),
and independent GCS bucket verification.
"""

import os
import re
import pytest
from pathlib import Path
import pandas as pd
import geopandas as gpd

from src.Ingestion.catalog_router import CatalogRouter
from src.Ingestion.data_importer import assert_tier2_physical_artifact_magic_bytes
from src.Ingestion.gcs_manager import DEFAULT_BUCKET, get_public_gcs_url
from src.Routing.corridor_extractor import CorridorExtractor
from runner.build_transit_report import compile_transit_report


def test_street_and_traffic_data_ingested_and_parquet_valid():
    """Verifies that real street network and live traffic tables exist in Parquet format with valid magic bytes."""
    router = CatalogRouter()
    
    streets_path = router.ensure_dataset("nsw_street_network")
    assert streets_path.exists(), f"Missing {streets_path}"
    assert_tier2_physical_artifact_magic_bytes(streets_path, min_bytes=1024)

    traffic_path = router.ensure_dataset("tfnsw_live_traffic_hazards")
    assert traffic_path.exists(), f"Missing {traffic_path}"
    assert_tier2_physical_artifact_magic_bytes(traffic_path, min_bytes=512)

    # Validate schema attributes
    streets_gdf = gpd.read_parquet(streets_path)
    assert not streets_gdf.empty
    assert "street_name" in streets_gdf.columns
    assert "am_peak_delay_pct" in streets_gdf.columns
    assert "traffic_variance_min" in streets_gdf.columns

    traffic_df = pd.read_parquet(traffic_path)
    assert not traffic_df.empty
    assert "headline" in traffic_df.columns
    assert "delay_minutes" in traffic_df.columns
    assert "affected_mode" in traffic_df.columns


def test_corridor_extractor_attaches_streets_and_traffic_variance():
    """Verifies that CorridorExtractor filters and attaches streets, hazards, and delay variance."""
    extractor = CorridorExtractor()
    corridor = extractor.extract_corridor("Maitland", "Newcastle University")

    assert "streets" in corridor
    assert "traffic_hazards" in corridor
    assert "traffic_variance_min" in corridor

    assert corridor["traffic_variance_min"] > 0.0, "Traffic variance must be non-zero"
    assert not corridor["streets"].empty, "Corridor streets GeoDataFrame must not be empty"
    assert not corridor["traffic_hazards"].empty, "Corridor traffic hazards must not be empty"


def test_no_carto_and_only_osm_esri_in_report(tmp_path):
    """Verifies that the compiled Map-in-a-Box report has strictly ZERO Carto references and uses OSM + Esri."""
    template_path = Path("runner/templates/map_in_a_box.html")
    assert template_path.exists()
    content = template_path.read_text(encoding="utf-8")

    # Strict check: No Carto tile URLs
    assert "cartocdn.com" not in content, "Found Carto CDN in template"
    assert "carto.com" not in content, "Found carto.com in template"

    # Must contain Esri and OpenStreetMap
    assert "arcgisonline.com" in content, "Must include Esri tile services"
    assert "openstreetmap.org" in content, "Must include OpenStreetMap tiles"


def test_dedicated_bucket_configured():
    """Verifies that GCS is configured to the independent project bucket, not rathmines."""
    assert DEFAULT_BUCKET == "nsw-transit-spatial-crafter"
    url = get_public_gcs_url("test.html")
    assert "nsw-transit-spatial-crafter" in url
    assert "rathmines" not in url
