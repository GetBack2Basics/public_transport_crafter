#!/usr/bin/env python3
"""
src/Query/gcs_query_engine.py
Universal GCS Transit Query & Bidirectional Timetable Optimization Engine.
Directly executes high-performance SQL queries on complete statewide NSW Parquet tables
in Google Cloud Storage (gs://nsw-transit-spatial-crafter/lake/nsw_*.parquet).
Solves full-day multi-modal transfers (Bus-to-Train, Bus-to-Bus, Train-to-Train)
and calculates actionable departure shift recommendations to achieve 5-15 minute transfer buffers.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np
import duckdb
import pyarrow.dataset as ds
import pyarrow.fs as pafs
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gcs_query_engine")

GCS_BUCKET = os.environ.get("GCS_BUCKET", "nsw-transit-spatial-crafter")


class GcsQueryEngine:
    """Connects to Google Cloud Storage Parquet lakehouse via DuckDB + PyArrow streaming."""

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket = bucket_name or GCS_BUCKET
        self.fs = pafs.GcsFileSystem(anonymous=False)
        self.con = duckdb.connect()
        self._register_statewide_tables()

    def _register_statewide_tables(self) -> None:
        """Registers the 5 statewide NSW transit tables directly from GCS."""
        tables = {
            "routes": f"{self.bucket}/lake/nsw_routes.parquet",
            "stops": f"{self.bucket}/lake/nsw_stops.parquet",
            "trips": f"{self.bucket}/lake/nsw_trips.parquet",
            "stop_times": f"{self.bucket}/lake/nsw_stop_times.parquet",
            "calendar": f"{self.bucket}/lake/nsw_calendar.parquet"
        }
        for tbl_name, gcs_path in tables.items():
            dataset = ds.dataset(gcs_path, filesystem=self.fs)
            self.con.register(tbl_name, dataset)
        logger.info(f"Registered statewide NSW transit tables from gs://{self.bucket}/lake/ in DuckDB")

    def build_transfer_sql(
        self,
        route_a: str,
        route_b: str,
        interchange_filter: Optional[str] = None,
        min_buffer_mins: int = 5,
        max_buffer_mins: int = 15,
        agency_id_a: Optional[str] = None,
        agency_id_b: Optional[str] = None
    ) -> str:
        """
        Dynamically constructs the parameterized full-day multi-modal transfer SQL query
        incorporating user-specified transfer windows, route names, and station filters.
        """
        where_a = [f"r.route_short_name = '{route_a}'"]
        if agency_id_a:
            where_a.append(f"r.agency_id = '{agency_id_a}'")
        where_a_str = " AND ".join(where_a)

        where_b = [f"r.route_short_name = '{route_b}'"]
        if agency_id_b:
            where_b.append(f"r.agency_id = '{agency_id_b}'")
        where_b_str = " AND ".join(where_b)

        stn_filter_sql = ""
        if interchange_filter:
            stn_filter_sql = f"AND (a.interchange ILIKE '%{interchange_filter}%' OR b.interchange ILIKE '%{interchange_filter}%')"

        sql = f"""
WITH route_a_events AS (
    SELECT 
        r.route_id          AS route_a_id,
        r.route_short_name  AS route_a,
        r.agency_id         AS agency_a,
        t.trip_id           AS trip_a_id,
        t.trip_headsign     AS headsign_a,
        t.direction_id      AS dir_a,
        s.stop_id           AS stop_a_id,
        s.stop_name         AS interchange,
        s.parent_station    AS parent_station_a,
        ('2026-10-24 00:00:00'::TIMESTAMP + to_seconds(CAST(split_part(st.arrival_time, ':', 1) AS INT) * 3600 + CAST(split_part(st.arrival_time, ':', 2) AS INT) * 60 + CAST(split_part(st.arrival_time, ':', 3) AS INT))) AS arr_a,
        ('2026-10-24 00:00:00'::TIMESTAMP + to_seconds(CAST(split_part(st.departure_time, ':', 1) AS INT) * 3600 + CAST(split_part(st.departure_time, ':', 2) AS INT) * 60 + CAST(split_part(st.departure_time, ':', 3) AS INT))) AS dep_a,
        st.stop_sequence    AS seq_a
    FROM routes r
    JOIN trips t       ON r.route_id = t.route_id
    JOIN stop_times st ON t.trip_id = st.trip_id
    JOIN stops s       ON st.stop_id = s.stop_id
    WHERE {where_a_str}
),
route_b_events AS (
    SELECT 
        r.route_id          AS route_b_id,
        r.route_short_name  AS route_b,
        r.agency_id         AS agency_b,
        t.trip_id           AS trip_b_id,
        t.trip_headsign     AS headsign_b,
        t.direction_id      AS dir_b,
        s.stop_id           AS stop_b_id,
        s.stop_name         AS interchange,
        s.parent_station    AS parent_station_b,
        ('2026-10-24 00:00:00'::TIMESTAMP + to_seconds(CAST(split_part(st.arrival_time, ':', 1) AS INT) * 3600 + CAST(split_part(st.arrival_time, ':', 2) AS INT) * 60 + CAST(split_part(st.arrival_time, ':', 3) AS INT))) AS arr_b,
        ('2026-10-24 00:00:00'::TIMESTAMP + to_seconds(CAST(split_part(st.departure_time, ':', 1) AS INT) * 3600 + CAST(split_part(st.departure_time, ':', 2) AS INT) * 60 + CAST(split_part(st.departure_time, ':', 3) AS INT))) AS dep_b,
        st.stop_sequence    AS seq_b
    FROM routes r
    JOIN trips t       ON r.route_id = t.route_id
    JOIN stop_times st ON t.trip_id = st.trip_id
    JOIN stops s       ON st.stop_id = s.stop_id
    WHERE {where_b_str}
)
SELECT 
    a.interchange,
    a.route_a,
    a.trip_a_id,
    a.headsign_a,
    strftime(a.arr_a, '%H:%M') AS a_arrival,
    strftime(a.dep_a, '%H:%M') AS a_departure,
    b.route_b,
    b.trip_b_id,
    b.headsign_b,
    strftime(b.arr_b, '%H:%M') AS b_arrival,
    strftime(b.dep_b, '%H:%M') AS b_departure,
    -- Direction 1: Transfer Route A -> Route B (A arrives before B departs)
    date_diff('minute', a.arr_a, b.dep_b) AS a_to_b_buffer_min,
    -- Direction 2: Transfer Route B -> Route A (B arrives before A departs)
    date_diff('minute', b.arr_b, a.dep_a) AS b_to_a_buffer_min,
    CASE 
        WHEN date_diff('minute', a.arr_a, b.dep_b) BETWEEN {min_buffer_mins} AND {max_buffer_mins} THEN 'OPTIMAL'
        WHEN date_diff('minute', a.arr_a, b.dep_b) > 0 AND date_diff('minute', a.arr_a, b.dep_b) < {min_buffer_mins} THEN 'TIGHT'
        ELSE 'LONG'
    END AS a_to_b_quality,
    CASE 
        WHEN date_diff('minute', b.arr_b, a.dep_a) BETWEEN {min_buffer_mins} AND {max_buffer_mins} THEN 'OPTIMAL'
        WHEN date_diff('minute', b.arr_b, a.dep_a) > 0 AND date_diff('minute', b.arr_b, a.dep_a) < {min_buffer_mins} THEN 'TIGHT'
        ELSE 'LONG'
    END AS b_to_a_quality
FROM route_a_events a
JOIN route_b_events b ON (
    a.stop_a_id = b.stop_b_id 
    OR (a.parent_station_a IS NOT NULL AND a.parent_station_a = b.parent_station_b)
    OR (a.interchange = b.interchange)
)
WHERE ((date_diff('minute', a.arr_a, b.dep_b) BETWEEN 0 AND 45)
    OR (date_diff('minute', b.arr_b, a.dep_a) BETWEEN 0 AND 45))
{stn_filter_sql}
ORDER BY a.interchange, a.arr_a, b.arr_b
"""
        return sql.strip()

    def execute_query(self, sql_query: str) -> pd.DataFrame:
        """Executes SQL against GCS via DuckDB and returns a pandas DataFrame."""
        logger.info("Executing transfer query against GCS lakehouse...")
        return self.con.execute(sql_query).df()

    def optimize_bidirectional_shifts(
        self,
        df_transfers: pd.DataFrame,
        route_a: str,
        route_b: str,
        min_buffer: int = 5,
        max_buffer: int = 15,
        target_buffer: int = 8
    ) -> pd.DataFrame:
        """
        Solves for the optimal departure shift (delta_t) for each trip of Route A
        to bring bidirectional transfer buffers into the [min_buffer, max_buffer] window
        across the full operating day.
        """
        if df_transfers.empty:
            return pd.DataFrame()

        recommendations = []
        trips = df_transfers["trip_a_id"].unique()

        for trip_id in trips:
            sub = df_transfers[df_transfers["trip_a_id"] == trip_id]
            interchange = sub["interchange"].iloc[0]
            headsign = sub["headsign_a"].iloc[0]
            base_arr = sub["a_arrival"].iloc[0]
            base_dep = sub["a_departure"].iloc[0]

            # Best matching connecting trip B
            # 1. Inbound: A arrives -> B departs
            inbound_matches = sub[sub["a_to_b_buffer_min"] >= 0]
            in_b_dep = inbound_matches["b_departure"].iloc[0] if not inbound_matches.empty else "N/A"
            current_in_buf = inbound_matches["a_to_b_buffer_min"].iloc[0] if not inbound_matches.empty else -1

            # 2. Outbound: B arrives -> A departs
            outbound_matches = sub[sub["b_to_a_buffer_min"] >= 0]
            out_b_arr = outbound_matches["b_arrival"].iloc[0] if not outbound_matches.empty else "N/A"
            current_out_buf = outbound_matches["b_to_a_buffer_min"].iloc[0] if not outbound_matches.empty else -1

            # Explore shift delta_t in [-15, +15] to bring both in [min_buffer, max_buffer]
            best_shift = 0
            best_cost = float("inf")

            for delta in range(-15, 16):
                cost = 0.0
                if current_in_buf >= 0:
                    new_in = current_in_buf - delta
                    if min_buffer <= new_in <= max_buffer:
                        cost += (new_in - target_buffer) ** 2
                    else:
                        cost += 100.0 + (new_in - target_buffer) ** 2

                if current_out_buf >= 0:
                    new_out = current_out_buf + delta
                    if min_buffer <= new_out <= max_buffer:
                        cost += (new_out - target_buffer) ** 2
                    else:
                        cost += 100.0 + (new_out - target_buffer) ** 2

                if cost < best_cost:
                    best_cost = cost
                    best_shift = delta

            # Calculate adjusted departure time
            dep_parts = list(map(int, base_dep.split(":")))
            dep_mins = dep_parts[0] * 60 + dep_parts[1] + best_shift
            dep_mins = dep_mins % (24 * 60)
            suggested_dep = f"{dep_mins // 60:02d}:{dep_mins % 60:02d}"

            opt_in_buf = current_in_buf - best_shift if current_in_buf >= 0 else -1
            opt_out_buf = current_out_buf + best_shift if current_out_buf >= 0 else -1

            status = "OPTIMAL" if (
                (opt_in_buf < 0 or min_buffer <= opt_in_buf <= max_buffer) and
                (opt_out_buf < 0 or min_buffer <= opt_out_buf <= max_buffer)
            ) else "TIGHT/LONG"

            recommendations.append({
                "interchange": interchange,
                "trip_id": trip_id,
                "headsign": headsign,
                "base_dep": base_dep,
                "suggested_dep": suggested_dep,
                "shift_min": f"{best_shift:+d}m",
                "connecting_route": route_b,
                "inbound_buffer": f"{opt_in_buf}m (target {min_buffer}-{max_buffer}m)" if opt_in_buf >= 0 else "N/A",
                "outbound_buffer": f"{opt_out_buf}m (target {min_buffer}-{max_buffer}m)" if opt_out_buf >= 0 else "N/A",
                "status": status
            })

        return pd.DataFrame(recommendations)
