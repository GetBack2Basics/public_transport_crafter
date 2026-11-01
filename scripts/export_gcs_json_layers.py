#!/usr/bin/env python3
"""
scripts/export_gcs_json_layers.py
Exports high-performance JSON context layers directly to GCS:
- gs://nsw-transit-spatial-crafter/lake/nsw_opal_station_patronage.json
- gs://nsw-transit-spatial-crafter/lake/nsw_corridor_congestion.json
- gs://nsw-transit-spatial-crafter/lake/nsw_interchanges.json
- gs://nsw-transit-spatial-crafter/config/catalog_manifest.json
Ensures the GCS-hosted web portal and any external client can query and consume everything from GCS.
"""

import json
import sys
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.Ingestion.gcs_manager import upload_file_to_gcs, get_active_gcs_bucket
from src.Ingestion.lake_io import get_lake_engine, publish_lake_json


def export_and_upload():
    bucket = get_active_gcs_bucket()
    print(f"Exporting JSON context layers for GCS portal (Bucket: gs://{bucket})...")

    con = get_lake_engine().con  # opal / congestion views backed by GCS Parquet

    # 1. Opal Station Patronage JSON
    df_opal = con.execute("SELECT * FROM opal").df()
    opal_dict = {}
    for _, row in df_opal.iterrows():
        st_key = str(row["clean_station_name"]).lower().strip()
        opal_dict[st_key] = {
            "clean_station_name": row["clean_station_name"],
            "total_monthly_trips": int(row["total_monthly_trips"]),
            "daily_avg_patronage": int(row["daily_avg_patronage"]),
            "statewide_rank": int(row["statewide_rank"])
        }
    publish_lake_json("nsw_opal_station_patronage.json", opal_dict, indent=2)
    print(f"Uploaded {len(opal_dict)} Opal stations to GCS JSON.")

    # 2. Road Congestion Variance JSON
    traffic_list = con.execute("SELECT * FROM congestion").df().to_dict(orient="records")
    publish_lake_json("nsw_corridor_congestion.json", traffic_list, indent=2)
    print(f"Uploaded {len(traffic_list)} road congestion corridors to GCS JSON.")

    # 3. Key Interchange Geometries JSON
    interchanges = {
        "morisset": {"name": "Morisset Station & Interchange", "lat": -33.1118, "lon": 151.4883, "region": "Hunter / Lake Macquarie", "rail_line": "CCN", "bus_routes": ["275", "98", "99"]},
        "fassifern": {"name": "Fassifern Station Interchange", "lat": -32.9984, "lon": 151.6033, "region": "Lake Macquarie", "rail_line": "CCN", "bus_routes": ["270", "271"]},
        "toronto": {"name": "Toronto Town Centre Interchange", "lat": -33.0135, "lon": 151.5947, "region": "Lake Macquarie", "rail_line": "None", "bus_routes": ["275", "270", "269"]},
        "chatswood": {"name": "Chatswood Transport Interchange", "lat": -33.7972, "lon": 151.1811, "region": "Northern Sydney", "rail_line": "T1 / T9 / Metro M1", "bus_routes": ["B1", "120", "267"]},
        "newcastle": {"name": "Newcastle Interchange (Wickham)", "lat": -32.9242, "lon": 151.7589, "region": "Newcastle", "rail_line": "CCN / HUN", "bus_routes": ["130", "131", "11"]},
        "maitland": {"name": "Maitland Railway Station", "lat": -32.7346, "lon": 151.5544, "region": "Hunter", "rail_line": "HUN", "bus_routes": ["181", "182", "183"]},
        "central": {"name": "Central Railway Station", "lat": -33.8824, "lon": 151.2062, "region": "Sydney CBD", "rail_line": "All Suburban & Intercity", "bus_routes": ["All"]},
        "parramatta": {"name": "Parramatta Transport Interchange", "lat": -33.8173, "lon": 151.0042, "region": "Western Sydney", "rail_line": "T1 / T2 / T5", "bus_routes": ["T80", "550", "600"]}
    }
    publish_lake_json("nsw_interchanges.json", interchanges, indent=2)
    print("Uploaded statewide interchange geometries to GCS JSON.")

    # 4. Catalog Manifest
    manifest_file = BASE_DIR / "config" / "catalog_manifest.json"
    if manifest_file.exists():
        upload_file_to_gcs(manifest_file, "config/catalog_manifest.json", content_type="application/json; charset=utf-8", cache_control="public, max-age=300")
        upload_file_to_gcs(manifest_file, "catalog_manifest.json", content_type="application/json; charset=utf-8", cache_control="public, max-age=300")
        print("Uploaded catalog_manifest.json to GCS.")

    print("\nAll JSON layers and catalog metadata successfully synchronized to GCS!")


if __name__ == "__main__":
    export_and_upload()
