#!/usr/bin/env python3
"""
scripts/build_active_route_geometries.py
Extracts the compact active route geometries dataset (~3-5 MB) containing
100% real GTFS stops and road-following polyline shapes for the most active corridors in NSW.
Includes:
- All pre-computed optimization corridors (275, 99, 880, 181, 270, 852, etc.)
- All routes with trip_count >= 30 across Greater Sydney, Hunter, Illawarra, Blue Mountains, Central Coast
- Specific user corridors (88, 275, etc.)
Outputs: data/lake/nsw_active_route_geometries.json
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

full_file = BASE_DIR / "data" / "lake" / "nsw_route_geometries.json"
catalog_file = BASE_DIR / "data" / "lake" / "nsw_routes_catalog.json"
out_file = BASE_DIR / "data" / "lake" / "nsw_active_route_geometries.json"

print("Loading full geometries and catalog...")
full_data = json.load(open(full_file, "r", encoding="utf-8"))
catalog = json.load(open(catalog_file, "r", encoding="utf-8"))

# Determine priority route_ids
priority_rids = set()
priority_short_names = {"275", "88", "880", "99", "181", "270", "852", "333", "370", "400", "420", "199", "144", "200", "B1", "T1", "T2", "T3", "T4", "T8", "CCN", "HUN", "SCO", "BMT"}

for r in catalog:
    rsn = str(r.get("route_short_name", "")).strip().upper()
    trip_cnt = r.get("trip_count", 0)
    if trip_cnt >= 25 or rsn in priority_short_names:
        priority_rids.add(str(r["route_id"]))

print(f"Total priority routes selected: {len(priority_rids)}")

active_geoms = {
    "by_route_id": {},
    "by_short_name": {}
}

raw_by_id = full_data.get("by_route_id", {})
for rid in priority_rids:
    if rid in raw_by_id:
        item = raw_by_id[rid]
        active_geoms["by_route_id"][rid] = item
        
        rsn_key = str(item["route_short_name"]).strip().upper()
        if rsn_key not in active_geoms["by_short_name"]:
            active_geoms["by_short_name"][rsn_key] = []
        active_geoms["by_short_name"][rsn_key].append(item)

# Also ensure any short names in priority_short_names are included
for rsn_key in priority_short_names:
    if rsn_key in full_data.get("by_short_name", {}) and rsn_key not in active_geoms["by_short_name"]:
        items = full_data["by_short_name"][rsn_key]
        active_geoms["by_short_name"][rsn_key] = items
        for item in items:
            active_geoms["by_route_id"][item["route_id"]] = item

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(active_geoms, f, separators=(',', ':'))

size_mb = out_file.stat().st_size / (1024 * 1024)
print(f"Wrote {out_file.name} ({size_mb:.2f} MB)")
print(f"Active routes by ID: {len(active_geoms['by_route_id'])}")
print(f"Active route short names: {len(active_geoms['by_short_name'])}")
