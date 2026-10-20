#!/usr/bin/env python3
"""
src/Routing/valhalla_client.py
Valhalla Ephemeral Routing Client & Pedestrian Catchment Generator.
Supports on-demand queries to ephemeral GCP routing instances (e2-custom-2-9216)
with dynamic NAT IP resolution, and fallback to geometric pedestrian isochrones.
Enforces Tier 2 Physical Artifact assertions on generated catchments.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, mapping
from shapely.ops import transform
import pyproj

from src.Ingestion.data_importer import assert_tier2_physical_artifact_magic_bytes
from src.Ingestion.gcs_manager import upload_file_to_gcs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("valhalla_client")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ISOCHRONE_DIR = BASE_DIR / "data" / "isochrones"


class ValhallaClient:
    """Client for pedestrian isochrone calculation using Valhalla API or calibrated walking buffers."""

    def __init__(self, host: Optional[str] = None, port: int = 8002):
        self.host = host or os.environ.get("VALHALLA_HOST", "")
        self.port = port
        ISOCHRONE_DIR.mkdir(parents=True, exist_ok=True)

    def is_valhalla_available(self) -> bool:
        """Checks if a live Valhalla routing daemon is responding at host:port."""
        if not self.host:
            return False
        try:
            resp = requests.get(f"http://{self.host}:{self.port}/status", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def compute_isochrones_for_stop(
        self,
        lat: float,
        lon: float,
        stop_id: str,
        stop_name: str,
        contours_minutes: List[int] = [5, 10, 15]
    ) -> gpd.GeoDataFrame:
        """
        Computes 5, 10, and 15-minute pedestrian walking catchments around a transit stop.
        If live Valhalla is responding, queries the API; otherwise computes metric walking buffers.
        """
        if self.is_valhalla_available():
            try:
                payload = {
                    "locations": [{"lat": lat, "lon": lon}],
                    "costing": "pedestrian",
                    "contours": [{"time": m, "color": "ff0000"} for m in contours_minutes],
                    "polygons": True
                }
                resp = requests.post(f"http://{self.host}:{self.port}/isochrone", json=payload, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")
                    gdf["stop_id"] = stop_id
                    gdf["stop_name"] = stop_name
                    logger.info(f"Retrieved live Valhalla isochrones for {stop_name}")
                    return gdf
            except Exception as e:
                logger.warning(f"Valhalla query failed ({e}); falling back to geometric pedestrian buffer.")

        # Authoritative Geodetic Walking Catchments (Standard 4.5 km/h = 75 meters/min)
        # 5 min -> 375m; 10 min -> 750m; 15 min -> 1125m
        wgs84 = pyproj.CRS("EPSG:4326")
        mga56 = pyproj.CRS("EPSG:7856")  # GDA2020 MGA Zone 56 (Metric NSW projection)
        project_to_metric = pyproj.Transformer.from_crs(wgs84, mga56, always_xy=True).transform
        project_to_wgs = pyproj.Transformer.from_crs(mga56, wgs84, always_xy=True).transform

        pt_wgs = Point(lon, lat)
        pt_mga = transform(project_to_metric, pt_wgs)

        features = []
        # Sort descending so 15-min polygon renders below 5-min polygon
        for minutes in sorted(contours_minutes, reverse=True):
            distance_meters = minutes * 75.0
            # Buffer in projected metric space
            buf_mga = pt_mga.buffer(distance_meters, resolution=32)
            # Reproject back to WGS84 for GeoJSON/MapLibre consumption
            buf_wgs = transform(project_to_wgs, buf_mga)

            features.append({
                "geometry": buf_wgs,
                "contour_minutes": minutes,
                "distance_meters": distance_meters,
                "stop_id": stop_id,
                "stop_name": stop_name,
                "mode": "pedestrian"
            })

        gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
        return gdf

    def generate_corridor_isochrones(self, stops_df: pd.DataFrame, corridor_tag: str = "corridor") -> Path:
        """
        Computes walking isochrones for all stops in the corridor and exports verified GeoParquet & GeoJSON.
        """
        all_gdfs = []
        for _, row in stops_df.iterrows():
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
            stop_id = str(row["stop_id"])
            stop_name = str(row["stop_name"])
            stop_gdf = self.compute_isochrones_for_stop(lat, lon, stop_id, stop_name)
            all_gdfs.append(stop_gdf)

        combined_gdf = pd.concat(all_gdfs, ignore_index=True)

        parquet_out = ISOCHRONE_DIR / f"{corridor_tag}_isochrones.parquet"
        geojson_out = ISOCHRONE_DIR / f"{corridor_tag}_isochrones.geojson"

        # Export GeoParquet
        combined_gdf.to_parquet(parquet_out, index=False)
        # Export GeoJSON
        combined_gdf.to_file(geojson_out, driver="GeoJSON")

        # TIER 2 Physical Magic Byte Assertion
        assert_tier2_physical_artifact_magic_bytes(parquet_out, min_bytes=2048)
        logger.info(f"Verified isochrone artifact: {parquet_out} ({parquet_out.stat().st_size} bytes)")

        # Sync to GCS cloud lakehouse
        upload_file_to_gcs(parquet_out, f"isochrones/{parquet_out.name}", content_type="application/octet-stream")
        upload_file_to_gcs(geojson_out, f"isochrones/{geojson_out.name}", content_type="application/geo+json")

        return parquet_out
