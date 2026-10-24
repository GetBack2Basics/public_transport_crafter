import sys
sys.path.insert(0, r"c:\Projects\nsw_public_transport_crafter\.venv\Lib\site-packages")
import duckdb
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

con = duckdb.connect()

print("=== Analyzing Distinct Route Short Names across NSW ===")
res = con.execute("""
    SELECT count(DISTINCT route_short_name) as distinct_names, count(*) as total_routes
    FROM 'data/lake/nsw_routes.parquet'
""").df()
print(res)

routes_df = con.execute("""
    SELECT 
        r.route_id,
        r.route_short_name,
        r.route_long_name,
        r.route_type,
        r.agency_id,
        count(t.trip_id) as trip_count
    FROM 'data/lake/nsw_routes.parquet' r
    LEFT JOIN 'data/lake/nsw_trips.parquet' t ON r.route_id = t.route_id
    GROUP BY r.route_id, r.route_short_name, r.route_long_name, r.route_type, r.agency_id
    ORDER BY trip_count DESC
""").df()

agency_map = {
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
    "2606": "Busways Central Coast",
    "SydneyTrains": "Sydney Trains",
    "NSWTrainLink": "NSW TrainLink",
    "SydneyMetro": "Sydney Metro",
    "NewcastleTransport": "Newcastle Transport",
    "BlueMountains": "Blue Mountains Transit"
}

mode_map = {
    0: "Light Rail",
    1: "Metro",
    2: "Heavy Rail",
    3: "Bus",
    4: "Ferry",
    700: "Bus Service",
    712: "School / Feeder Bus",
    714: "Regional Coach"
}

# Group by lowercase route_short_name
route_index = {}
all_short_names = set()

for _, row in routes_df.iterrows():
    rsn = str(row["route_short_name"]).strip()
    if not rsn or rsn.lower() == "none":
        continue
    all_short_names.add(rsn)
    key = rsn.lower()
    if key not in route_index:
        route_index[key] = {
            "route_short_name": rsn,
            "corridors": []
        }
    
    agency_id = str(row["agency_id"])
    route_type = int(row["route_type"]) if str(row["route_type"]).isdigit() else 3
    
    route_index[key]["corridors"].append({
        "route_id": str(row["route_id"]),
        "agency_id": agency_id,
        "agency_name": agency_map.get(agency_id, f"NSW Operator ({agency_id})"),
        "route_long_name": str(row["route_long_name"]),
        "mode": mode_map.get(route_type, "Bus"),
        "trip_count": int(row["trip_count"]) if row["trip_count"] else 0
    })

print(f"Total distinct route short names: {len(route_index):,}")

# Save compact route index
out_file = BASE_DIR / "data" / "lake" / "nsw_route_lookup_index.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(route_index, f)

print(f"Wrote {out_file} ({out_file.stat().st_size / 1024:.1f} KB)")
