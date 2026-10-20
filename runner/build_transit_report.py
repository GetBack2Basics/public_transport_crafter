#!/usr/bin/env python3
"""
runner/build_transit_report.py
FunGIS Map-in-a-Box Compiler.
Compiles baseline vs. optimized transit schedules, pedestrian walking isochrones,
and client-side AlaSQL tables into a standalone, offline-first HTML report.
Zero running backend required.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd
import geopandas as gpd

from src.Ingestion.gcs_manager import upload_file_to_gcs, get_public_gcs_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_transit_report")

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "runner" / "templates" / "map_in_a_box.html"
REPORT_OUTPUT_DIR = BASE_DIR / "data" / "reports"


def dataframe_to_clean_records(df: Optional[pd.DataFrame]) -> list:
    """Converts a DataFrame to JSON-serializable list of dicts."""
    if df is None or df.empty:
        return []
    cleaned = df.copy()
    if isinstance(cleaned, gpd.GeoDataFrame) and "geometry" in cleaned:
        cleaned = cleaned.drop(columns=["geometry"])
    if "geom_orig" in cleaned:
        cleaned = cleaned.drop(columns=["geom_orig"])
    return cleaned.to_dict(orient="records")


def geodataframe_to_geojson_dict(gdf: Any) -> Dict[str, Any]:
    """Converts a GeoDataFrame or DataFrame to GeoJSON dict in EPSG:4326."""
    if gdf is None or (hasattr(gdf, "empty") and gdf.empty):
        return {"type": "FeatureCollection", "features": []}
    
    reproj = gdf.copy()
    if not isinstance(reproj, gpd.GeoDataFrame):
        if "stop_lat" in reproj and "stop_lon" in reproj:
            from shapely.geometry import Point
            geometry = [Point(xy) for xy in zip(reproj["stop_lon"], reproj["stop_lat"])]
            reproj = gpd.GeoDataFrame(reproj, geometry=geometry, crs="EPSG:4326")
        elif "geometry" in reproj:
            reproj = gpd.GeoDataFrame(reproj, geometry="geometry", crs="EPSG:4326")
        else:
            return {"type": "FeatureCollection", "features": []}

    if hasattr(reproj, "crs") and reproj.crs and reproj.crs.to_string() != "EPSG:4326":
        reproj = reproj.to_crs("EPSG:4326")
    
    if "geom_orig" in reproj:
        reproj = reproj.drop(columns=["geom_orig"])
        
    return json.loads(reproj.to_json())


def compile_transit_report(
    query_string: str,
    corridor_data: Dict[str, Any],
    optimization_results: Dict[str, Any],
    isochrones_gdf: Optional[gpd.GeoDataFrame] = None,
    opal_df: Optional[pd.DataFrame] = None,
    output_filename: str = "transit_insight_report.html"
) -> Path:
    """
    Compiles data and templates using the FunGIS {{PLACEHOLDER}} pattern.
    """
    REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORT_OUTPUT_DIR / output_filename

    assert TEMPLATE_PATH.exists(), f"Template missing at {TEMPLATE_PATH}"
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template_content = f.read()

    orig_name = corridor_data["origin"]["name"]
    dest_name = corridor_data["destination"]["name"]
    interchange_name = corridor_data["interchange"]["name"]

    # Convert payloads
    stops_gdf = corridor_data.get("stops")
    stops_geojson = geodataframe_to_geojson_dict(stops_gdf)
    isochrones_geojson = geodataframe_to_geojson_dict(isochrones_gdf)

    trips_records = dataframe_to_clean_records(optimization_results.get("optimized_trips_df"))
    base_transfers_records = dataframe_to_clean_records(optimization_results.get("baseline_transfers_df"))
    opt_transfers_records = dataframe_to_clean_records(optimization_results.get("optimized_transfers_df"))
    opal_records = dataframe_to_clean_records(opal_df)

    metrics_payload = {
        "baseline_metrics": optimization_results.get("baseline_metrics", {}),
        "optimized_metrics": optimization_results.get("optimized_metrics", {}),
        "resource_delta": optimization_results.get("resource_delta", {})
    }

    # Replace placeholders
    rendered = template_content
    rendered = rendered.replace("{{REPORT_TITLE}}", f"Transit Optimization: {orig_name} to {dest_name}")
    rendered = rendered.replace("{{QUERY_STRING}}", query_string)
    rendered = rendered.replace("{{ORIGIN_NAME}}", orig_name)
    rendered = rendered.replace("{{DESTINATION_NAME}}", dest_name)
    rendered = rendered.replace("{{INTERCHANGE_NAME}}", interchange_name)
    rendered = rendered.replace("{{GENERATED_TIMESTAMP}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S AEST"))

    rendered = rendered.replace("{{METRICS_JSON}}", json.dumps(metrics_payload))
    rendered = rendered.replace("{{STOPS_GEOJSON}}", json.dumps(stops_geojson))
    rendered = rendered.replace("{{ISOCHRONES_GEOJSON}}", json.dumps(isochrones_geojson))
    rendered = rendered.replace("{{TRIPS_JSON}}", json.dumps(trips_records))
    rendered = rendered.replace("{{BASELINE_TRANSFERS_JSON}}", json.dumps(base_transfers_records))
    rendered = rendered.replace("{{OPTIMIZED_TRANSFERS_JSON}}", json.dumps(opt_transfers_records))
    rendered = rendered.replace("{{OPAL_LOADINGS_JSON}}", json.dumps(opal_records))

    # Assert no unreplaced template tokens remain (e.g. {{TOKEN}})
    import re
    unreplaced = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
    assert not unreplaced, f"Found unreplaced {{PLACEHOLDER}} tokens in compiled HTML: {unreplaced}"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    # Physical file assertion
    assert output_path.exists(), f"HTML report was not written to {output_path}"
    file_size = output_path.stat().st_size
    assert file_size > 4096, f"HTML report is too small: {file_size} bytes"

    logger.info(f"Successfully compiled Map-in-a-Box report: {output_path} ({file_size} bytes)")

    # Automatically deploy to Google Cloud Storage for review
    gcs_review_url = upload_file_to_gcs(
        output_path,
        gcs_blob_path=f"reports/{output_filename}",
        content_type="text/html",
        cache_control="public, max-age=60"
    )
    upload_file_to_gcs(
        output_path,
        gcs_blob_path="transit_insight_report.html",
        content_type="text/html",
        cache_control="public, max-age=60"
    )
    logger.info(f"Published GCS review deliverable: {gcs_review_url}")
    return output_path


def main():
    logger.info("Executing standalone test compilation...")
    # Test stub for build runner
    demo_corridor = {
        "origin": {"name": "Maitland Station", "lat": -32.73602, "lon": 151.55431},
        "destination": {"name": "University of Newcastle", "lat": -32.89420, "lon": 151.70510},
        "interchange": {"name": "Hamilton Station Interchange"}
    }
    demo_results = {
        "baseline_metrics": {"avg_wait_minutes": 22.4, "pct_optimal_window": 12.5, "peak_vehicle_requirement": 4},
        "optimized_metrics": {"avg_wait_minutes": 6.8, "pct_optimal_window": 87.5, "peak_vehicle_requirement": 4},
        "resource_delta": {"wait_time_reduction_minutes": 15.6, "optimal_transfer_increase_pct": 75.0, "penalty_reduction_pct": 82.4}
    }
    path = compile_transit_report("Test Corridor Query", demo_corridor, demo_results)
    print(f"Report compiled at: {path}")


if __name__ == "__main__":
    main()
