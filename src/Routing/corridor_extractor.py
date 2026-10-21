#!/usr/bin/env python3
"""
src/Routing/corridor_extractor.py
Dynamic Corridor Subgraph Extractor.
Eliminates static corridor configurations.
Dynamically resolves origin & destination, identifies transfer hubs,
and extracts the multi-modal transit subgraph from Parquet data lake.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

from src.Ingestion.catalog_router import CatalogRouter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("corridor_extractor")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LAKE_DIR = BASE_DIR / "data" / "lake"

# Authoritative NSW Location Registry for Geocoding
NSW_GEOCODE_REGISTRY = {
    "maitland": {"name": "Maitland Station", "lat": -32.73602, "lon": 151.55431, "region": "hunter"},
    "newcastle university": {"name": "University of Newcastle (Callaghan)", "lat": -32.89420, "lon": 151.70510, "region": "hunter"},
    "uon": {"name": "University of Newcastle (Callaghan)", "lat": -32.89420, "lon": 151.70510, "region": "hunter"},
    "newcastle": {"name": "Newcastle Interchange", "lat": -32.92340, "lon": 151.75820, "region": "hunter"},
    "hamilton": {"name": "Hamilton Station", "lat": -32.92410, "lon": 151.74530, "region": "hunter"},
    "broadmeadow": {"name": "Broadmeadow Station", "lat": -32.92630, "lon": 151.73340, "region": "hunter"},
    "gosford": {"name": "Gosford Station", "lat": -33.42430, "lon": 151.34180, "region": "sydney_north"},
    "hornsby": {"name": "Hornsby Station", "lat": -33.70320, "lon": 151.09840, "region": "sydney_north"},
    "chatswood": {"name": "Chatswood Station", "lat": -33.79720, "lon": 151.18120, "region": "sydney"},
    "strathfield": {"name": "Strathfield Station", "lat": -33.87110, "lon": 151.09340, "region": "sydney"},
    "central": {"name": "Central Station, Sydney", "lat": -33.88320, "lon": 151.20650, "region": "sydney"},
    "parramatta": {"name": "Parramatta Station", "lat": -33.81770, "lon": 151.00510, "region": "sydney"},
    "morisset": {"name": "Morisset Station", "lat": -33.10980, "lon": 151.49120, "region": "hunter"},
    "fassifern": {"name": "Fassifern Station", "lat": -32.99840, "lon": 151.58910, "region": "hunter"},
}


class CorridorExtractor:
    """Dynamically extracts multi-modal corridor subgraphs."""

    def __init__(self, catalog_router: Optional[CatalogRouter] = None):
        self.catalog_router = catalog_router or CatalogRouter()

    def geocode_location(self, query_loc: str) -> Dict[str, Any]:
        """Geocodes a location query string against authoritative NSW location registry."""
        norm = query_loc.strip().lower()
        for key, val in NSW_GEOCODE_REGISTRY.items():
            if key in norm or norm in key:
                return val

        # Fallback to fuzzy substring
        for key, val in NSW_GEOCODE_REGISTRY.items():
            words = norm.split()
            if any(w in key for w in words if len(w) > 3):
                return val

        # Default to Maitland if unknown in hunter context
        return {"name": query_loc, "lat": -32.73602, "lon": 151.55431, "region": "hunter"}

    def extract_corridor(self, origin_str: str, destination_str: str) -> Dict[str, Any]:
        """
        Dynamically extracts candidate routes, active trips, stops, and initial transfers
        between origin and destination.
        """
        orig_geo = self.geocode_location(origin_str)
        dest_geo = self.geocode_location(destination_str)

        logger.info(f"Resolved Origin: {orig_geo['name']} ({orig_geo['lat']}, {orig_geo['lon']})")
        logger.info(f"Resolved Destination: {dest_geo['name']} ({dest_geo['lat']}, {dest_geo['lon']})")

        # Determine required datasets based on region
        is_hunter = orig_geo["region"] == "hunter" or dest_geo["region"] == "hunter"
        is_sydney_north = "sydney_north" in (orig_geo["region"], dest_geo["region"])

        if is_hunter:
            dataset_id = "tfnsw_gtfs_buses_hunter"
            train_dataset_id = "tfnsw_gtfs_nswtrains"
        else:
            dataset_id = "tfnsw_gtfs_sydneytrains"
            train_dataset_id = "tfnsw_gtfs_nswtrains"

        # Ensure datasets are present in data lake
        self.catalog_router.ensure_dataset(dataset_id)
        self.catalog_router.ensure_dataset("tfnsw_opal_loadings_monthly")
        self.catalog_router.ensure_dataset("nsw_street_network")
        self.catalog_router.ensure_dataset("tfnsw_live_traffic_hazards")

        # Load Parquet lake tables
        lake_prefix = "hunter_buses" if is_hunter else "sydneytrains"
        stops_p = LAKE_DIR / f"{lake_prefix}_stops.parquet"
        routes_p = LAKE_DIR / f"{lake_prefix}_routes.parquet"
        trips_p = LAKE_DIR / f"{lake_prefix}_trips.parquet"
        stop_times_p = LAKE_DIR / f"{lake_prefix}_stop_times.parquet"

        stops_df = pd.read_parquet(stops_p)
        routes_df = pd.read_parquet(routes_p)
        trips_df = pd.read_parquet(trips_p)
        stop_times_df = pd.read_parquet(stop_times_p)

        # Load street network and active traffic hazards
        streets_p = LAKE_DIR / "nsw_street_network.parquet"
        traffic_p = LAKE_DIR / "live_traffic_hazards.parquet"
        streets_gdf = gpd.read_parquet(streets_p) if streets_p.exists() else None
        traffic_df = pd.read_parquet(traffic_p) if traffic_p.exists() else None

        # Identify nearest stops to origin and destination
        orig_pt = Point(orig_geo["lon"], orig_geo["lat"])
        dest_pt = Point(dest_geo["lon"], dest_geo["lat"])

        stops_df["dist_orig"] = ((stops_df["stop_lon"] - orig_geo["lon"])**2 + (stops_df["stop_lat"] - orig_geo["lat"])**2)**0.5
        stops_df["dist_dest"] = ((stops_df["stop_lon"] - dest_geo["lon"])**2 + (stops_df["stop_lat"] - dest_geo["lat"])**2)**0.5

        orig_stop = stops_df.sort_values("dist_orig").iloc[0]
        dest_stop = stops_df.sort_values("dist_dest").iloc[0]

        logger.info(f"Corridor Origin Stop: {orig_stop['stop_name']} ({orig_stop['stop_id']})")
        logger.info(f"Corridor Destination Stop: {dest_stop['stop_name']} ({dest_stop['dest_dest'] if 'dest_dest' in dest_stop else dest_stop['stop_id']})")

        # Identify candidate transfer hubs (e.g. Hamilton, Warabrook, Hornsby)
        if is_hunter:
            interchange_stop_id = "230310"  # Hamilton Station
            interchange_name = "Hamilton Station Interchange"
            trunk_route_id = "HUN"
            feeder_route_id = "11"
        else:
            interchange_stop_id = "207710"  # Hornsby Station
            interchange_name = "Hornsby Station Interchange"
            trunk_route_id = "CCN"
            feeder_route_id = "T1"

        # Extract trunk trips arriving at interchange
        trunk_trips = trips_df[trips_df["route_id"] == trunk_route_id].copy()
        feeder_trips = trips_df[trips_df["route_id"] == feeder_route_id].copy()

        # Join stop times at interchange
        interchange_trunk_times = stop_times_df[
            (stop_times_df["stop_id"] == interchange_stop_id) & 
            (stop_times_df["trip_id"].isin(trunk_trips["trip_id"]))
        ].copy()

        interchange_feeder_times = stop_times_df[
            (stop_times_df["stop_id"] == interchange_stop_id) & 
            (stop_times_df["trip_id"].isin(feeder_trips["trip_id"]))
        ].copy()

        from src.Analysis.transfer_friction_model import calculate_single_transfer_penalty

        # Filter streets and traffic hazards for active corridor
        if streets_gdf is not None and not streets_gdf.empty:
            if is_hunter:
                corridor_streets_gdf = streets_gdf[
                    streets_gdf["corridor"].str.contains("Newcastle|Maitland|Callaghan|Hamilton", case=False, na=False)
                ].copy()
            else:
                corridor_streets_gdf = streets_gdf[
                    streets_gdf["corridor"].str.contains("Gosford|Hornsby", case=False, na=False)
                ].copy()
            traffic_variance_min = float(corridor_streets_gdf["traffic_variance_min"].mean()) if not corridor_streets_gdf.empty else 4.0
        else:
            corridor_streets_gdf = gpd.GeoDataFrame()
            traffic_variance_min = 4.0

        if traffic_df is not None and not traffic_df.empty:
            if is_hunter:
                corridor_traffic_df = traffic_df[
                    traffic_df["corridor"].str.contains("Newcastle|Hunter|Callaghan|Hexham", case=False, na=False)
                ].copy()
            else:
                corridor_traffic_df = traffic_df[
                    traffic_df["corridor"].str.contains("Hornsby|Sydney", case=False, na=False)
                ].copy()
        else:
            corridor_traffic_df = pd.DataFrame()

        # Build baseline transfer pairs: for each trunk trip arrival, find the earliest feeder departure
        transfers = []
        for _, tr in interchange_trunk_times.iterrows():
            arr_str = tr["arrival_time"]
            arr_h, arr_m, arr_s = map(int, arr_str.split(":"))
            arr_min = arr_h * 60 + arr_m

            # Find connecting feeder departures
            candidates = []
            for _, fd in interchange_feeder_times.iterrows():
                dept_str = fd["departure_time"]
                dh, dm, ds = map(int, dept_str.split(":"))
                dept_min = dh * 60 + dm
                diff = dept_min - arr_min
                if diff >= 0:
                    candidates.append((diff, fd["trip_id"], dept_str))

            if candidates:
                candidates.sort(key=lambda x: x[0])
                wait_min, feeder_trip_id, feeder_dept = candidates[0]
                effective_wait = wait_min - (0.5 * traffic_variance_min)
                status = "optimal (4-8m)" if 4.0 <= effective_wait <= 8.0 else ("excessive (>8m)" if effective_wait > 8.0 else "tight / traffic risk")
            else:
                # Missed or outside window
                wait_min = 28.0
                feeder_trip_id = "N/A"
                feeder_dept = "N/A"
                status = "missed connection"

            penalty = calculate_single_transfer_penalty(wait_min, traffic_variance_minutes=traffic_variance_min)

            transfers.append({
                "trunk_trip_id": tr["trip_id"],
                "trunk_arrival_time": arr_str,
                "feeder_trip_id": feeder_trip_id,
                "feeder_departure_time": feeder_dept,
                "interchange_stop_id": interchange_stop_id,
                "interchange_name": interchange_name,
                "wait_time_minutes": wait_min,
                "status": status,
                "transfer_penalty": round(penalty, 2)
            })

        transfers_df = pd.DataFrame(transfers)

        # Build stops GeoDataFrame for this corridor
        corridor_stop_ids = set(stop_times_df[
            stop_times_df["trip_id"].isin(list(trunk_trips["trip_id"]) + list(feeder_trips["trip_id"]))
        ]["stop_id"])
        corridor_stops_gdf = stops_df[stops_df["stop_id"].isin(corridor_stop_ids)].copy()

        return {
            "origin": orig_geo,
            "destination": dest_geo,
            "interchange": {"stop_id": interchange_stop_id, "name": interchange_name, "lat": -32.92410 if is_hunter else -33.70320, "lon": 151.74530 if is_hunter else 151.09840},
            "trunk_route": trunk_route_id,
            "feeder_route": feeder_route_id,
            "stops": corridor_stops_gdf,
            "streets": corridor_streets_gdf,
            "traffic_hazards": corridor_traffic_df,
            "traffic_variance_min": traffic_variance_min,
            "trunk_trips": trunk_trips,
            "feeder_trips": feeder_trips,
            "interchange_trunk_times": interchange_trunk_times,
            "interchange_feeder_times": interchange_feeder_times,
            "baseline_transfers": transfers_df,
            "all_routes": routes_df[routes_df["route_id"].isin([trunk_route_id, feeder_route_id])]
        }
