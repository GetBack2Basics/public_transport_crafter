#!/usr/bin/env python3
"""
scripts/extract_all_route_geometries.py
Extracts 100% REAL GTFS stops and road-following polyline shapes for all NSW transit routes.
Sources:
1. data/lake/nsw_routes.parquet, nsw_trips.parquet, nsw_stop_times.parquet, nsw_stops.parquet
2. shapes.txt from data/cache/nsw_gtfs_complete.zip
Generates data/lake/nsw_route_geometries.json
"""

import sys
sys.path.insert(0, r"c:\Projects\nsw_public_transport_crafter\.venv\Lib\site-packages")
from shapely.geometry import LineString
import duckdb
import zipfile
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

con = duckdb.connect()

print("=== 1. Extracting representative trips and stops from Parquet ===")
t0 = time.time()
q_rep = """
WITH trip_counts AS (
    SELECT t.route_id, r.route_short_name, r.route_long_name, r.agency_id, r.route_type,
           t.trip_id, t.shape_id, count(st.stop_sequence) as stop_count,
           ROW_NUMBER() OVER (PARTITION BY t.route_id ORDER BY count(st.stop_sequence) DESC) as rn
    FROM 'data/lake/nsw_trips.parquet' t
    JOIN 'data/lake/nsw_routes.parquet' r ON t.route_id = r.route_id
    JOIN 'data/lake/nsw_stop_times.parquet' st ON t.trip_id = st.trip_id
    GROUP BY t.route_id, r.route_short_name, r.route_long_name, r.agency_id, r.route_type, t.trip_id, t.shape_id
)
SELECT tc.route_id, tc.route_short_name, tc.route_long_name, tc.agency_id, tc.route_type,
       tc.trip_id, tc.shape_id, tc.stop_count
FROM trip_counts tc
WHERE tc.rn = 1 AND tc.shape_id IS NOT NULL AND tc.shape_id != ''
"""
df_rep = con.execute(q_rep).df()
print(f"Found {len(df_rep)} representative route trips in {time.time()-t0:.2f}s")

# Extract ordered stops for all these representative trips
print("=== 2. Extracting ordered stops for representative trips ===")
t1 = time.time()
q_stops = f"""
WITH rep_trips AS ({q_rep})
SELECT rt.route_id, st.stop_sequence, s.stop_id, s.stop_name, s.stop_lat, s.stop_lon
FROM rep_trips rt
JOIN 'data/lake/nsw_stop_times.parquet' st ON rt.trip_id = st.trip_id
JOIN 'data/lake/nsw_stops.parquet' s ON st.stop_id = s.stop_id
ORDER BY rt.route_id, st.stop_sequence
"""
df_stops = con.execute(q_stops).df()
print(f"Extracted {len(df_stops):,} stops in {time.time()-t1:.2f}s")

# Group stops by route_id
route_stops_map = {}
for _, row in df_stops.iterrows():
    rid = row['route_id']
    if rid not in route_stops_map:
        route_stops_map[rid] = []
    route_stops_map[rid].append({
        "stop_id": str(row['stop_id']),
        "name": str(row['stop_name']),
        "lat": round(float(row['stop_lat']), 6),
        "lon": round(float(row['stop_lon']), 6),
        "seq": int(row['stop_sequence'])
    })

# Identify target shape IDs to extract
target_shapes = set(df_rep['shape_id'])
print(f"=== 3. Extracting and simplifying road shape polylines for {len(target_shapes)} shapes from shapes.txt ===")
t2 = time.time()

raw_shapes = {s: [] for s in target_shapes}
with zipfile.ZipFile(BASE_DIR / 'data' / 'cache' / 'nsw_gtfs_complete.zip') as z:
    with z.open('shapes.txt') as f:
        f.readline() # header
        for line in f:
            line_str = line.decode('utf-8').strip()
            if not line_str:
                continue
            parts = [p.strip('"') for p in line_str.split(',')]
            sid = parts[0]
            if sid in raw_shapes:
                raw_shapes[sid].append((float(parts[2]), float(parts[1]), int(parts[3]))) # lon, lat, seq

print(f"Read shapes in {time.time()-t2:.2f}s. Now simplifying geometries...")
t3 = time.time()

# Simplify geometries using Douglas-Peucker (0.00008 deg ~ 8 meters)
simplified_shapes = {}
for sid, pts in raw_shapes.items():
    if len(pts) < 2:
        continue
    pts.sort(key=lambda x: x[2])
    coords = [(p[0], p[1]) for p in pts]
    try:
        ls = LineString(coords)
        simp = ls.simplify(0.00008, preserve_topology=True)
        # Convert to [lat, lon] for Leaflet
        simplified_shapes[sid] = [[round(p[1], 6), round(p[0], 6)] for p in simp.coords]
    except Exception as e:
        simplified_shapes[sid] = [[round(p[1], 6), round(p[0], 6)] for p in coords]

print(f"Simplified {len(simplified_shapes)} shapes in {time.time()-t3:.2f}s")

# Build final route index
# Store by route_id and group by route_short_name
agency_names = {
    "2450": "CDC Hunter / Hunter Valley Buses",
    "2455": "Premier Illawarra",
    "2501": "Busways Western Sydney",
    "2502": "Interline Bus Services",
    "2503": "Transit Systems West",
    "2504": "CDC NSW (Hillsbus)",
    "2507": "Forest Coach Lines",
    "2508": "Keolis Downer Northern Beaches",
    "2509": "Transdev John Holland",
    "2510": "U-Go Mobility",
    "2606": "Busways Central Coast"
}

route_geometries = {
    "by_route_id": {},
    "by_short_name": {}
}

for _, r in df_rep.iterrows():
    rid = str(r['route_id'])
    rsn = str(r['route_short_name']).strip()
    sid = str(r['shape_id'])
    agency_id = str(r['agency_id'])
    agency = agency_names.get(agency_id, f"NSW Transit Operator ({agency_id})")

    geom = simplified_shapes.get(sid, [])
    stops = route_stops_map.get(rid, [])

    if not geom and stops:
        # Fallback to stop points if shape was missing
        geom = [[s['lat'], s['lon']] for s in stops]

    if not geom:
        continue

    # Calculate bounding box
    lats = [p[0] for p in geom]
    lons = [p[1] for p in geom]
    bounds = [[round(min(lats) - 0.008, 5), round(min(lons) - 0.008, 5)],
              [round(max(lats) + 0.008, 5), round(max(lons) + 0.008, 5)]]

    item = {
        "route_id": rid,
        "route_short_name": rsn,
        "route_long_name": str(r['route_long_name']),
        "agency_id": agency_id,
        "agency_name": agency,
        "trip_id": str(r['trip_id']),
        "shape_id": sid,
        "stop_count": len(stops),
        "geom_count": len(geom),
        "bounds": bounds,
        "route_geometry": geom,
        "stops": stops
    }

    route_geometries["by_route_id"][rid] = item

    rsn_key = rsn.upper()
    if rsn_key not in route_geometries["by_short_name"]:
        route_geometries["by_short_name"][rsn_key] = []
    
    route_geometries["by_short_name"][rsn_key].append(item)

out_file = BASE_DIR / "data" / "lake" / "nsw_route_geometries.json"
print(f"=== 4. Writing {out_file} ===")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(route_geometries, f, separators=(',', ':'))

file_size_mb = out_file.stat().st_size / (1024 * 1024)
print(f"Done! Written {out_file.name} ({file_size_mb:.2f} MB)")
print(f"Total routes with road geometry: {len(route_geometries['by_route_id']):,}")
print(f"Total distinct route short names: {len(route_geometries['by_short_name']):,}")
