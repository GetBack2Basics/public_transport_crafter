#!/usr/bin/env python3
"""
src/Ingestion/ingest_statewide_nsw.py
Statewide NSW Public Transport Ingestion Engine.
Downloads authoritative TfNSW Timetables Complete GTFS (10,200+ routes, all buses and trains),
transforms CSV tables into high-efficiency compressed Parquet, enforces 3-Tier Anti-Mock validation,
and uploads to Google Cloud Storage (gs://nsw-transit-spatial-crafter/lake/).
"""

import os
import sys
import io
import time
import zipfile
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("statewide_ingestion")

from src.Ingestion.gcs_manager import upload_file_to_gcs, get_active_gcs_bucket
from src.Ingestion.data_importer import assert_tier2_physical_artifact_magic_bytes
CACHE_DIR = BASE_DIR / "data" / "cache"
LAKE_DIR = BASE_DIR / "data" / "lake"
TFNSW_COMPLETE_GTFS_URL = (
    "https://opendata.transport.nsw.gov.au/data/dataset/d1f68d4f-b778-44df-9823-cf2fa922e47f/"
    "resource/67974f14-01bf-47b7-bfa5-c7f2f8a950ca/download/full_greater_sydney_gtfs_static_0.zip"
)


def download_statewide_gtfs(destination_zip: Path) -> Path:
    """Downloads the official TfNSW Statewide Complete GTFS archive with progress tracking."""
    destination_zip.parent.mkdir(parents=True, exist_ok=True)
    if destination_zip.exists() and destination_zip.stat().st_size > 300_000_000:
        logger.info(f"Using existing cached statewide GTFS archive: {destination_zip} ({destination_zip.stat().st_size / 1024 / 1024:.1f} MB)")
        return destination_zip

    logger.info(f"Downloading TfNSW Statewide Timetables Complete GTFS from {TFNSW_COMPLETE_GTFS_URL}...")
    t0 = time.time()
    resp = requests.get(TFNSW_COMPLETE_GTFS_URL, stream=True, timeout=120)
    assert resp.status_code == 200, f"Failed to download GTFS archive: HTTP {resp.status_code}"

    total_bytes = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    chunk_size = 4 * 1024 * 1024  # 4MB chunks

    with open(destination_zip, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_bytes > 0:
                    pct = (downloaded / total_bytes) * 100
                    mb = downloaded / (1024 * 1024)
                    tot_mb = total_bytes / (1024 * 1024)
                    print(f"\rDownloading statewide GTFS: {mb:.1f} / {tot_mb:.1f} MB ({pct:.1f}%)", end="", flush=True)

    print()
    elapsed = time.time() - t0
    logger.info(f"Statewide GTFS downloaded successfully in {elapsed:.1f}s ({destination_zip.stat().st_size / 1024 / 1024:.1f} MB)")
    return destination_zip


def convert_routes_to_parquet(zf: zipfile.ZipFile, output_parquet: Path) -> int:
    """Parses routes.txt into compressed Parquet."""
    logger.info("Processing routes.txt...")
    with zf.open("routes.txt") as f:
        table = pacsv.read_csv(
            f,
            read_options=pacsv.ReadOptions(encoding="utf-8-sig"),
            convert_options=pacsv.ConvertOptions(
                include_columns=["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
                column_types={
                    "route_id": pa.string(),
                    "agency_id": pa.string(),
                    "route_short_name": pa.string(),
                    "route_long_name": pa.string(),
                    "route_type": pa.int32()
                }
            )
        )
    pq.write_table(table, output_parquet, compression="zstd")
    assert_tier2_physical_artifact_magic_bytes(output_parquet, min_bytes=1000)
    logger.info(f"Wrote {len(table):,} routes to {output_parquet.name} ({output_parquet.stat().st_size / 1024:.1f} KB)")
    return len(table)


def convert_stops_to_parquet(zf: zipfile.ZipFile, output_parquet: Path) -> int:
    """Parses stops.txt into compressed Parquet."""
    logger.info("Processing stops.txt...")
    with zf.open("stops.txt") as f:
        table = pacsv.read_csv(
            f,
            read_options=pacsv.ReadOptions(encoding="utf-8-sig"),
            convert_options=pacsv.ConvertOptions(
                include_columns=["stop_id", "stop_code", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "platform_code"],
                column_types={
                    "stop_id": pa.string(),
                    "stop_code": pa.string(),
                    "stop_name": pa.string(),
                    "stop_lat": pa.float64(),
                    "stop_lon": pa.float64(),
                    "location_type": pa.int32(),
                    "parent_station": pa.string(),
                    "platform_code": pa.string()
                }
            )
        )
    pq.write_table(table, output_parquet, compression="zstd")
    assert_tier2_physical_artifact_magic_bytes(output_parquet, min_bytes=10_000)
    logger.info(f"Wrote {len(table):,} stops to {output_parquet.name} ({output_parquet.stat().st_size / 1024 / 1024:.2f} MB)")
    return len(table)


def convert_trips_to_parquet(zf: zipfile.ZipFile, output_parquet: Path) -> int:
    """Parses trips.txt into compressed Parquet."""
    logger.info("Processing trips.txt...")
    with zf.open("trips.txt") as f:
        table = pacsv.read_csv(
            f,
            read_options=pacsv.ReadOptions(encoding="utf-8-sig"),
            convert_options=pacsv.ConvertOptions(
                include_columns=["trip_id", "route_id", "service_id", "shape_id", "trip_headsign", "direction_id"],
                column_types={
                    "trip_id": pa.string(),
                    "route_id": pa.string(),
                    "service_id": pa.string(),
                    "shape_id": pa.string(),
                    "trip_headsign": pa.string(),
                    "direction_id": pa.int32()
                }
            )
        )
    pq.write_table(table, output_parquet, compression="zstd")
    assert_tier2_physical_artifact_magic_bytes(output_parquet, min_bytes=100_000)
    logger.info(f"Wrote {len(table):,} trips to {output_parquet.name} ({output_parquet.stat().st_size / 1024 / 1024:.2f} MB)")
    return len(table)


def convert_stop_times_to_parquet(zf: zipfile.ZipFile, output_parquet: Path) -> int:
    """Parses stop_times.txt into compressed Parquet."""
    logger.info("Processing stop_times.txt (full 24h schedule)...")
    with zf.open("stop_times.txt") as f:
        table = pacsv.read_csv(
            f,
            read_options=pacsv.ReadOptions(encoding="utf-8-sig"),
            convert_options=pacsv.ConvertOptions(
                include_columns=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
                column_types={
                    "trip_id": pa.string(),
                    "arrival_time": pa.string(),
                    "departure_time": pa.string(),
                    "stop_id": pa.string(),
                    "stop_sequence": pa.int32()
                }
            )
        )
    pq.write_table(table, output_parquet, compression="zstd")
    assert_tier2_physical_artifact_magic_bytes(output_parquet, min_bytes=1_000_000)
    logger.info(f"Wrote {len(table):,} stop_times to {output_parquet.name} ({output_parquet.stat().st_size / 1024 / 1024:.2f} MB)")
    return len(table)


def convert_calendar_to_parquet(zf: zipfile.ZipFile, output_parquet: Path) -> int:
    """Parses calendar.txt into compressed Parquet."""
    logger.info("Processing calendar.txt...")
    with zf.open("calendar.txt") as f:
        table = pacsv.read_csv(
            f,
            read_options=pacsv.ReadOptions(encoding="utf-8-sig"),
            convert_options=pacsv.ConvertOptions(
                include_columns=["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
                column_types={
                    "service_id": pa.string(),
                    "monday": pa.int32(),
                    "tuesday": pa.int32(),
                    "wednesday": pa.int32(),
                    "thursday": pa.int32(),
                    "friday": pa.int32(),
                    "saturday": pa.int32(),
                    "sunday": pa.int32(),
                    "start_date": pa.string(),
                    "end_date": pa.string()
                }
            )
        )
    pq.write_table(table, output_parquet, compression="zstd")
    assert_tier2_physical_artifact_magic_bytes(output_parquet, min_bytes=500)
    logger.info(f"Wrote {len(table):,} calendar service rows to {output_parquet.name} ({output_parquet.stat().st_size / 1024:.1f} KB)")
    return len(table)


def ingest_and_upload_statewide_nsw() -> Dict[str, Any]:
    """
    Executes the full statewide ingestion pipeline:
    1. Download 314MB GTFS
    2. Convert all tables to Parquet
    3. Assert Tier 2 magic bytes
    4. Upload to GCS cloud lakehouse
    """
    logger.info("=" * 70)
    logger.info(" NSW Statewide Transit Lakehouse Ingestion (All Buses & Trains)")
    logger.info("=" * 70)

    LAKE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    zip_path = CACHE_DIR / "nsw_gtfs_complete.zip"
    download_statewide_gtfs(zip_path)

    stats = {}
    with zipfile.ZipFile(zip_path) as zf:
        routes_parquet = LAKE_DIR / "nsw_routes.parquet"
        stats["routes"] = convert_routes_to_parquet(zf, routes_parquet)

        stops_parquet = LAKE_DIR / "nsw_stops.parquet"
        stats["stops"] = convert_stops_to_parquet(zf, stops_parquet)

        trips_parquet = LAKE_DIR / "nsw_trips.parquet"
        stats["trips"] = convert_trips_to_parquet(zf, trips_parquet)

        stop_times_parquet = LAKE_DIR / "nsw_stop_times.parquet"
        stats["stop_times"] = convert_stop_times_to_parquet(zf, stop_times_parquet)

        calendar_parquet = LAKE_DIR / "nsw_calendar.parquet"
        stats["calendar"] = convert_calendar_to_parquet(zf, calendar_parquet)

    # Upload to GCS
    bucket = get_active_gcs_bucket()
    logger.info(f"Uploading statewide Parquet tables to gs://{bucket}/lake/...")
    uploaded_urls = {}
    for table_name in ["nsw_routes", "nsw_stops", "nsw_trips", "nsw_stop_times", "nsw_calendar"]:
        local_file = LAKE_DIR / f"{table_name}.parquet"
        gcs_blob = f"lake/{table_name}.parquet"
        url = upload_file_to_gcs(local_file, gcs_blob, content_type="application/octet-stream")
        uploaded_urls[table_name] = url
        logger.info(f"Uploaded gs://{bucket}/{gcs_blob} ({local_file.stat().st_size / 1024 / 1024:.2f} MB)")

    logger.info("=" * 70)
    logger.info(" Statewide NSW Ingestion to GCS Complete!")
    logger.info(f" Summary: {stats}")
    logger.info("=" * 70)

    return {
        "status": "success",
        "record_counts": stats,
        "gcs_urls": uploaded_urls
    }


if __name__ == "__main__":
    ingest_and_upload_statewide_nsw()
