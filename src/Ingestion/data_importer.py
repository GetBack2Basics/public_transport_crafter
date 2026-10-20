#!/usr/bin/env python3
"""
src/Ingestion/data_importer.py
Single reusable, config-driven ingestion engine for NSW Transit datasets.
Strictly enforces the GetBack2Basics 3-Tier Anti-Mock Defense Model:
  Tier 1: Pre-Execution Contract Assertion
  Tier 2: Physical Artifact & Magic Bytes Assertion (b'PAR1')
  Tier 3: Deep Response & Error Inspection
"""

import os
import sys
import io
import json
import zipfile
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
import pyarrow.parquet as pq
from dotenv import load_dotenv

# Load local environment variables (.env)
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_importer")

REQUIRED_CONFIG_KEYS = [
    "source_id", "protocol", "endpoint", "format", "target_tables", "destination"
]

TRUSTED_TFNSW_DOMAIN = "https://api.transport.nsw.gov.au/"


def assert_tier1_pre_execution_contract(config: Dict[str, Any]) -> None:
    """
    TIER 1: Pre-Execution Contract Assertion.
    Validates endpoint authenticity, credentials, and configuration contract schema.
    """
    for key in REQUIRED_CONFIG_KEYS:
        assert key in config, f"TIER 1 VIOLATION: Missing required config key '{key}'"

    protocol = config["protocol"]
    endpoint = config["endpoint"]

    if protocol == "tfnsw_api":
        assert endpoint.startswith(TRUSTED_TFNSW_DOMAIN), (
            f"TIER 1 VIOLATION: Illegal untrusted endpoint: {endpoint}. "
            f"Must start with {TRUSTED_TFNSW_DOMAIN}"
        )
        api_key = os.environ.get("TFNSW_API_KEY", "")
        # Expand environment variables in headers if present
        headers = config.get("headers", {})
        auth_header = headers.get("Authorization", "")
        if "${TFNSW_API_KEY}" in auth_header:
            assert len(api_key) > 8, (
                "TIER 1 VIOLATION: Missing or invalid TfNSW API token in TFNSW_API_KEY environment variable. "
                "Register at https://opendata.transport.nsw.gov.au to obtain a free production API token."
            )
    elif protocol == "local_file":
        source_path = Path(endpoint)
        assert source_path.exists(), f"TIER 1 VIOLATION: Source file does not exist: {source_path}"
    else:
        raise AssertionError(f"TIER 1 VIOLATION: Unsupported protocol: {protocol}")

    assert config["format"] in ["gtfs_zip", "csv", "json"], f"Unsupported format: {config['format']}"


def assert_tier3_deep_response_inspection(resp: requests.Response) -> None:
    """
    TIER 3: Deep Response & Error Inspection.
    Validates HTTP status code, Content-Type, and deep payload error attributes.
    Prevents masked HTML error pages (e.g. 200 OK with CSRF or SSO login HTML).
    """
    assert resp.status_code == 200, f"TIER 3 VIOLATION: Upstream API HTTP error: {resp.status_code} - {resp.text[:300]}"
    
    content_type = resp.headers.get("Content-Type", "").lower()
    allowed_types = ["application/json", "application/zip", "application/octet-stream", "application/x-zip-compressed", "text/csv"]
    
    # Check if content type matches allowed binary/data streams
    assert any(at in content_type for at in allowed_types), (
        f"TIER 3 VIOLATION: Received invalid Content-Type '{content_type}'. "
        f"Possible masked HTML landing page or SSO challenge."
    )

    if "application/json" in content_type:
        try:
            body = resp.json()
        except Exception as e:
            raise AssertionError(f"TIER 3 VIOLATION: Failed to parse upstream JSON body: {e}")
        assert "error" not in body and "fault" not in body, (
            f"TIER 3 VIOLATION: Upstream API reported error inside 200 OK body: {body}"
        )


def assert_tier2_physical_artifact_magic_bytes(parquet_path: Path, min_bytes: int = 4096) -> None:
    """
    TIER 2: Physical Artifact & Magic Bytes Assertion.
    Verifies file physical presence on disk, minimum non-empty byte size,
    and exact Parquet binary magic bytes: b'PAR1'.
    """
    assert parquet_path.exists(), f"TIER 2 VIOLATION: Physical artifact not found on disk: {parquet_path}"
    file_size = parquet_path.stat().st_size
    assert file_size >= min_bytes, (
        f"TIER 2 VIOLATION: Physical artifact {parquet_path} is undersized ({file_size} bytes < {min_bytes} min_bytes). "
        f"Indicates partial download or empty table write."
    )

    with open(parquet_path, "rb") as f:
        magic = f.read(4)
        assert magic == b"PAR1", f"TIER 2 VIOLATION: File failed Parquet magic bytes header check: {magic} != b'PAR1'"
        f.seek(-4, io.SEEK_END)
        footer_magic = f.read(4)
        assert footer_magic == b"PAR1", (
            f"TIER 2 VIOLATION: File failed Parquet footer magic check: {footer_magic} != b'PAR1'"
        )

    # Validate schema readable by PyArrow
    try:
        parquet_file = pq.ParquetFile(parquet_path)
        assert parquet_file.metadata.num_rows > 0, f"TIER 2 VIOLATION: Parquet file has 0 rows: {parquet_path}"
    except Exception as e:
        raise AssertionError(f"TIER 2 VIOLATION: Parquet schema validation failed: {e}")


def parse_and_process_gtfs_zip(zip_bytes: bytes, config: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """
    Parses GTFS zip payload, extracts requested tables, reprojects geometries,
    and returns a mapping of table_name -> DataFrame.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        available_files = z.namelist()
        logger.info(f"GTFS Zip archive opened. Files: {available_files[:10]}...")

        extracted_tables = {}
        for table in config.get("target_tables", ["routes", "trips", "stop_times", "stops"]):
            txt_name = f"{table}.txt"
            if txt_name in available_files:
                with z.open(txt_name) as f:
                    df = pd.read_csv(f, dtype=str)
                    extracted_tables[table] = df
                    logger.info(f"Loaded {table}: {len(df)} rows")
            else:
                logger.warning(f"Requested table '{txt_name}' not found in GTFS archive")

        # Load shapes if present
        if "shapes.txt" in available_files and "shapes" in config.get("target_tables", []):
            with z.open("shapes.txt") as f:
                shapes_df = pd.read_csv(f)
                extracted_tables["shapes"] = shapes_df

        # Load calendar if present
        if "calendar.txt" in available_files and "calendar" in config.get("target_tables", []):
            with z.open("calendar.txt") as f:
                calendar_df = pd.read_csv(f, dtype=str)
                extracted_tables["calendar"] = calendar_df

    # Spatial transformation for stops if present
    if "stops" in extracted_tables:
        stops_df = extracted_tables["stops"]
        stops_df["stop_lat"] = pd.to_numeric(stops_df["stop_lat"], errors="coerce")
        stops_df["stop_lon"] = pd.to_numeric(stops_df["stop_lon"], errors="coerce")
        stops_df = stops_df.dropna(subset=["stop_lat", "stop_lon"])

        geometry = [Point(xy) for xy in zip(stops_df["stop_lon"], stops_df["stop_lat"])]
        output_crs = config.get("output_crs", "EPSG:7856")
        gdf_stops = gpd.GeoDataFrame(stops_df, geometry=geometry, crs="EPSG:4326")
        
        # Reproject if requested
        if output_crs != "EPSG:4326":
            gdf_stops["geom_orig"] = gdf_stops["geometry"]
            gdf_stops = gdf_stops.to_crs(output_crs)

        extracted_tables["stops"] = gdf_stops

    # Filter criteria application (e.g. route_ids, bounding_box)
    filter_crit = config.get("filter_criteria", {})
    route_ids = filter_crit.get("route_ids", [])
    if route_ids and "routes" in extracted_tables:
        extracted_tables["routes"] = extracted_tables["routes"][extracted_tables["routes"]["route_id"].isin(route_ids)]
        if "trips" in extracted_tables:
            extracted_tables["trips"] = extracted_tables["trips"][extracted_tables["trips"]["route_id"].isin(route_ids)]
            valid_trip_ids = set(extracted_tables["trips"]["trip_id"])
            if "stop_times" in extracted_tables:
                extracted_tables["stop_times"] = extracted_tables["stop_times"][extracted_tables["stop_times"]["trip_id"].isin(valid_trip_ids)]

    return extracted_tables


def export_tables_to_parquet(tables: Dict[str, pd.DataFrame], destination: Path) -> List[Path]:
    """
    Writes extracted tables to Parquet / GeoParquet files and verifies Tier 2 magic bytes.
    Creates both individual table files and a unified master Parquet at destination.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    generated_paths = []

    # If destination specifies a .parquet file, we write individual tables into destination directory
    # or create companion files, and consolidate a unified trips/stops index at destination.
    dest_stem = destination.stem
    dest_dir = destination.parent

    for table_name, df in tables.items():
        table_path = dest_dir / f"{dest_stem}_{table_name}.parquet"
        if isinstance(df, gpd.GeoDataFrame):
            df.to_parquet(table_path, index=False)
        else:
            df.to_parquet(table_path, index=False, engine="pyarrow")
        
        assert_tier2_physical_artifact_magic_bytes(table_path, min_bytes=512)
        generated_paths.append(table_path)
        logger.info(f"Exported {table_name} to {table_path} ({table_path.stat().st_size} bytes)")

    # Consolidate primary corridor index at main destination path
    # Joining trips with routes and stop_times count if present
    if "trips" in tables:
        primary_df = tables["trips"].copy()
        if "routes" in tables:
            route_subset = tables["routes"][["route_id", "route_short_name", "route_long_name"]].drop_duplicates()
            primary_df = primary_df.merge(route_subset, on="route_id", how="left")
        primary_df.to_parquet(destination, index=False, engine="pyarrow")
    elif "stops" in tables:
        tables["stops"].to_parquet(destination, index=False)
    else:
        # Fallback to first table
        first_table = list(tables.values())[0]
        first_table.to_parquet(destination, index=False)

    assert_tier2_physical_artifact_magic_bytes(destination, min_bytes=1024)
    generated_paths.append(destination)
    logger.info(f"Verified primary physical artifact: {destination} ({destination.stat().st_size} bytes, magic: b'PAR1')")
    return generated_paths


def run_ingestion(config_path_or_dict: Any) -> List[Path]:
    """
    Main entrypoint for dynamic ingestion engine.
    Executes 3-Tier anti-mock validation and writes verified Parquet lake files.
    """
    if isinstance(config_path_or_dict, (str, Path)):
        with open(config_path_or_dict, "r", encoding="utf-8") as f:
            raw_text = f.read()
            # Replace environment variables like ${TFNSW_API_KEY}
            for env_k, env_v in os.environ.items():
                raw_text = raw_text.replace(f"${{{env_k}}}", env_v)
            config = json.loads(raw_text)
    else:
        config = config_path_or_dict

    # 1. TIER 1: Pre-Execution Contract Assertion
    assert_tier1_pre_execution_contract(config)
    logger.info(f"Tier 1 Contract Asserted: {config['source_id']} -> {config['endpoint']}")

    protocol = config["protocol"]
    destination = Path(config["destination"])

    # 2. Fetch Upstream Data
    if protocol == "tfnsw_api":
        headers = config.get("headers", {})
        # Substitute API Key in header if needed
        for hk, hv in list(headers.items()):
            if "${TFNSW_API_KEY}" in hv:
                headers[hk] = hv.replace("${TFNSW_API_KEY}", os.environ.get("TFNSW_API_KEY", ""))

        resp = requests.get(config["endpoint"], headers=headers, timeout=60)
        # 3. TIER 3: Deep Response & Error Inspection
        assert_tier3_deep_response_inspection(resp)
        payload_bytes = resp.content
    elif protocol == "local_file":
        with open(config["endpoint"], "rb") as f:
            payload_bytes = f.read()

    # 4. Parse & Transform
    fmt = config["format"]
    if fmt == "gtfs_zip":
        tables = parse_and_process_gtfs_zip(payload_bytes, config)
    elif fmt == "csv":
        df = pd.read_csv(io.BytesIO(payload_bytes))
        tables = {config.get("target_tables", ["dataset"])[0]: df}
    elif fmt == "json":
        data = json.loads(payload_bytes.decode("utf-8"))
        df = pd.DataFrame(data)
        tables = {config.get("target_tables", ["dataset"])[0]: df}
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    # 5. Export to Parquet & assert TIER 2 Physical Magic Bytes
    artifacts = export_tables_to_parquet(tables, destination)
    return artifacts


def main():
    parser = argparse.ArgumentParser(description="NSW Transit Dynamic Data Importer with 3-Tier Anti-Mock Verification")
    parser.add_argument("--config", required=True, help="Path to static or dynamically generated JSON config")
    args = parser.parse_args()

    artifacts = run_ingestion(args.config)
    print(f"SUCCESS: Generated {len(artifacts)} verified Parquet artifacts:")
    for art in artifacts:
        print(f"  - {art} ({art.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
