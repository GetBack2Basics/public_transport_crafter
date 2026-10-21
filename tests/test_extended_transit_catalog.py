"""
tests/test_extended_transit_catalog.py
Validates extended NSW transit catalog feeds:
- Regional Coaches (NSW TrainLink)
- Sydney Metro City & Southwest (M1)
- Greater Sydney Buses (B-Line Northern Beaches)
- Blue Mountains Transit
- Illawarra & Wollongong Buses
Asserts schema compliance, Tier 2 magic bytes, and dynamic corridor extraction.
"""

import json
import pytest
from pathlib import Path
import pandas as pd
import geopandas as gpd

from src.Ingestion.catalog_router import CatalogRouter
from src.Ingestion.data_importer import assert_tier2_physical_artifact_magic_bytes
from src.Routing.corridor_extractor import CorridorExtractor

BASE_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = BASE_DIR / "config" / "catalog_manifest.json"


def test_catalog_manifest_contains_new_feeds():
    """Validates that catalog manifest includes all newly integrated transit feeds."""
    assert MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    datasets = manifest["datasets"]
    required_new_feeds = [
        "tfnsw_gtfs_coaches_regional",
        "tfnsw_gtfs_metro_city_southwest",
        "tfnsw_gtfs_buses_greater_sydney",
        "tfnsw_gtfs_buses_bluemountains",
        "tfnsw_gtfs_buses_illawarra",
    ]

    for feed_id in required_new_feeds:
        assert feed_id in datasets, f"Missing feed '{feed_id}' in catalog manifest"
        feed_meta = datasets[feed_id]
        assert feed_meta["protocol"] == "tfnsw_api"
        assert feed_meta["endpoint"].startswith("https://api.transport.nsw.gov.au/")
        assert feed_meta["format"] == "gtfs_zip"
        assert "stops" in feed_meta["target_tables"]
        assert "routes" in feed_meta["target_tables"]
        assert "trips" in feed_meta["target_tables"]
        assert "stop_times" in feed_meta["target_tables"]
        assert feed_meta["default_destination"].startswith("data/lake/")


def test_extended_feeds_ingestion_and_tier2_magic_bytes():
    """Asserts that each extended feed is ingested into valid Parquet lake files with b'PAR1' magic bytes."""
    router = CatalogRouter()
    required_new_feeds = [
        "tfnsw_gtfs_coaches_regional",
        "tfnsw_gtfs_metro_city_southwest",
        "tfnsw_gtfs_buses_greater_sydney",
        "tfnsw_gtfs_buses_bluemountains",
        "tfnsw_gtfs_buses_illawarra",
    ]

    for feed_id in required_new_feeds:
        target_path = router.ensure_dataset(feed_id)
        assert target_path.exists(), f"Target file missing for {feed_id}: {target_path}"
        assert_tier2_physical_artifact_magic_bytes(target_path, min_bytes=1024)

        dest_dir = target_path.parent
        stem = target_path.stem

        # Verify companion tables
        stops_p = dest_dir / f"{stem}_stops.parquet"
        routes_p = dest_dir / f"{stem}_routes.parquet"
        trips_p = dest_dir / f"{stem}_trips.parquet"
        stop_times_p = dest_dir / f"{stem}_stop_times.parquet"

        for comp_p in [stops_p, routes_p, trips_p, stop_times_p]:
            assert comp_p.exists(), f"Companion table missing: {comp_p}"
            assert_tier2_physical_artifact_magic_bytes(comp_p, min_bytes=512)

        stops_df = pd.read_parquet(stops_p)
        assert not stops_df.empty
        assert "stop_id" in stops_df.columns
        assert "stop_name" in stops_df.columns
        assert "stop_lat" in stops_df.columns
        assert "stop_lon" in stops_df.columns

        # Verify coordinates fall within NSW bounding box
        assert stops_df["stop_lat"].between(-38.0, -28.0).all()
        assert stops_df["stop_lon"].between(140.0, 154.0).all()


def test_corridor_extraction_regional_coaches():
    """Verifies CorridorExtractor resolves Dubbo to Lithgow via Regional Coach network."""
    extractor = CorridorExtractor()
    corridor = extractor.extract_corridor("Dubbo", "Lithgow")

    assert corridor["trunk_route"] == "591"
    assert corridor["feeder_route"] == "592"
    assert corridor["interchange"]["name"] == "Lithgow Station Interchange"
    assert len(corridor["baseline_transfers"]) > 0
    assert not corridor["stops"].empty


def test_corridor_extraction_sydney_metro():
    """Verifies CorridorExtractor resolves Sydney Metro M1 City & Southwest corridor."""
    extractor = CorridorExtractor()
    corridor = extractor.extract_corridor("Tallawong", "Barangaroo")

    assert corridor["trunk_route"] == "M1"
    assert corridor["interchange"]["name"] == "Chatswood Metro Interchange"
    assert len(corridor["baseline_transfers"]) > 0
    assert not corridor["stops"].empty


def test_corridor_extraction_blue_mountains():
    """Verifies CorridorExtractor resolves Blue Mountains bus connections."""
    extractor = CorridorExtractor()
    corridor = extractor.extract_corridor("Springwood", "Katoomba")

    assert corridor["trunk_route"] == "690"
    assert corridor["feeder_route"] == "686"
    assert corridor["interchange"]["name"] == "Katoomba Station Interchange"
    assert len(corridor["baseline_transfers"]) > 0
    assert not corridor["stops"].empty


def test_corridor_extraction_illawarra():
    """Verifies CorridorExtractor resolves Wollongong to UOW bus network."""
    extractor = CorridorExtractor()
    corridor = extractor.extract_corridor("Wollongong", "University of Wollongong")

    assert corridor["trunk_route"] == "9"
    assert corridor["feeder_route"] == "55A"
    assert corridor["interchange"]["name"] == "Wollongong Station Interchange"
    assert len(corridor["baseline_transfers"]) > 0
    assert not corridor["stops"].empty


def test_corridor_extraction_greater_sydney_bline():
    """Verifies CorridorExtractor resolves Northern Beaches B-Line to Wynyard corridor."""
    extractor = CorridorExtractor()
    corridor = extractor.extract_corridor("Mona Vale", "Wynyard")

    assert corridor["trunk_route"] == "B1"
    assert corridor["interchange"]["name"] == "Wynyard Station Interchange"
    assert len(corridor["baseline_transfers"]) > 0
    assert not corridor["stops"].empty
