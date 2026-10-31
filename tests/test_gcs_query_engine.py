"""
tests/test_gcs_query_engine.py
Unit and integration tests for GCS Query Engine and Intent Clarifier.
Validates:
- Parameterized SQL query generation incorporating transfer windows and stations
- Multi-region and multi-route ambiguity detection with clarifying questions
- Bidirectional timetable shift optimization logic
"""

import pytest
import pandas as pd
from src.Query.intent_clarifier import IntentClarifier
from src.Query.gcs_query_engine import GcsQueryEngine


def test_intent_clarifier_ambiguity_detection():
    clarifier = IntentClarifier()

    # Query with ambiguous single route
    analysis = clarifier.analyze_intent("how can we optimize bus 275")
    assert not analysis["is_complete"]
    assert len(analysis["clarifications_needed"]) >= 1

    # Check that route was extracted
    assert "275" in analysis["detected_routes"]


def test_intent_clarifier_custom_transfer_window():
    clarifier = IntentClarifier()

    # Query specifying a custom transfer window (4 to 10 mins)
    analysis = clarifier.analyze_intent("connect 275 to CCN at Morisset with 4-10 min buffer")
    assert analysis["transfer_window"]["min_minutes"] == 4
    assert analysis["transfer_window"]["max_minutes"] == 10
    assert "Morisset" in analysis["detected_stations"]


def test_sql_query_builder_parameterization():
    # Build query without network connection to test SQL syntax
    engine = GcsQueryEngine.__new__(GcsQueryEngine)
    sql = engine.build_transfer_sql(
        route_a="275",
        route_b="270",
        interchange_filter="Toronto",
        min_buffer_mins=4,
        max_buffer_mins=12,
        agency_id_a="2450"
    )

    assert "r.route_short_name = '275'" in sql
    assert "r.route_short_name = '270'" in sql
    assert "r.agency_id = '2450'" in sql
    assert "BETWEEN 4 AND 12" in sql
    assert "Toronto" in sql


def test_bidirectional_shift_optimizer():
    engine = GcsQueryEngine.__new__(GcsQueryEngine)

    # Sample mock connection data to verify math
    mock_df = pd.DataFrame([{
        "interchange": "Morisset Station",
        "trip_a_id": "TRIP_01",
        "headsign_a": "Morisset",
        "a_arrival": "07:00",
        "a_departure": "07:05",
        "route_b": "CCN",
        "b_departure": "07:08",
        "b_arrival": "07:20",
        "a_to_b_buffer_min": 8,
        "b_to_a_buffer_min": 15
    }])

    opt_df = engine.optimize_bidirectional_shifts(
        mock_df,
        route_a="275",
        route_b="CCN",
        min_buffer=5,
        max_buffer=15,
        target_buffer=8
    )

    assert not opt_df.empty
    assert opt_df.iloc[0]["status"] == "OPTIMAL"
    assert "inbound_buffer" in opt_df.columns
    assert "outbound_buffer" in opt_df.columns


def test_spatial_route_geometry_and_1km_infrastructure():
    import json
    from pathlib import Path
    opts_file = Path("data/lake/nsw_timetable_optimizations.json")
    assert opts_file.exists(), "nsw_timetable_optimizations.json must exist"

    with open(opts_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "275_cdc_hunter_morisset" in data
    assert "275_interline_liverpool" in data
    assert "275_forest_chatswood" in data

    for key in ["275_cdc_hunter_morisset", "275_interline_liverpool", "275_forest_chatswood"]:
        sc = data[key]
        assert "map" in sc
        m = sc["map"]
        assert "route_geometry" in m
        assert len(m["route_geometry"]) >= 400, f"{key} route_geometry must follow actual road network (>400 pts), got {len(m['route_geometry'])}"
        assert "infrastructure" in m
        assert len(m["infrastructure"]) > 0, f"{key} must have detected infrastructure within 1km"
        
        # Verify distance constraint (all within 1000m)
        for infra in m["infrastructure"]:
            assert infra["distance_m"] <= 1000, f"Infrastructure {infra['name']} exceeds 1000m: {infra['distance_m']}"
            assert infra["mode"] in ["train", "metro", "ferry", "bus"]
            assert len(infra["name"]) > 0
            assert -38.0 <= infra["lat"] <= -28.0
            assert 140.0 <= infra["lon"] <= 155.0

        # Verify analytics and scenario simulations
        assert "analytics" in sc
        assert "buffer_distribution" in sc["analytics"]
        assert "hourly_frequency" in sc["analytics"]
        assert "performance_metrics" in sc["analytics"]

        assert "scenario_actions" in sc or "ai_suggested_steps" in sc
        steps = sc.get("scenario_actions") or sc.get("ai_suggested_steps")
        assert len(steps) >= 3
        for step in steps:
            assert "title" in step
            assert "prompt" in step
            assert len(step["title"]) > 0
            assert len(step["prompt"]) > 0


def test_universal_route_parsing_and_nearest_options():
    """
    Requirement 2.1:
    Verify that route parsing works universally for any route number (not hardcoded to 275 or 99),
    and if a route does not exist (e.g. 9999, 7777), it explicitly reports that route X doesn't exist
    and returns nearest options Y.
    """
    clarifier = IntentClarifier("data/lake/nsw_route_lookup_index.json")
    assert len(clarifier.route_index) >= 5000, f"Expected >= 5000 routes in lookup index, got {len(clarifier.route_index)}"

    # 1. Test existing routes across NSW
    for r in ["99", "275", "852", "181", "333", "B1", "T1", "CCN"]:
        res = clarifier.analyze_intent(f"how can we optimize route {r} to connect with the train")
        assert r in res["detected_routes"], f"Route {r} was not detected"
        status = res["route_status"].get(r)
        assert status is not None, f"Status missing for {r}"
        assert status["exists"] is True, f"Route {r} should exist in NSW catalog"
        assert len(status["corridors"]) >= 1, f"Route {r} should have at least 1 corridor"

    # Specific check for route 99 having 2 operators (Premier Illawarra & Busways Central Coast)
    r99_status = clarifier.route_status = clarifier.analyze_intent("optimize route 99")["route_status"]["99"]
    agencies_99 = [c["agency_name"] for c in r99_status["corridors"]]
    assert any("Premier" in a for a in agencies_99)
    assert any("Busways" in a for a in agencies_99)

    # 2. Test non-existent route numbers (e.g. 9999, 7777)
    res_9999 = clarifier.analyze_intent("how can we optimize route 9999 to connect with the train")
    assert "9999" in res_9999["detected_routes"]
    status_9999 = res_9999["route_status"]["9999"]
    assert status_9999["exists"] is False, "Route 9999 should NOT exist in NSW GTFS"
    assert "does not exist in the NSW transit lakehouse" in status_9999["message"]
    assert len(status_9999["nearest_options"]) >= 3
    # Nearest options for 9999 must include 99
    assert "99" in status_9999["nearest_options"], f"Expected '99' in nearest options for 9999, got {status_9999['nearest_options']}"

    # Route 7777 check
    res_7777 = clarifier.analyze_intent("check service 7777 at interchange")
    assert "7777" in res_7777["detected_routes"]
    status_7777 = res_7777["route_status"]["7777"]
    assert status_7777["exists"] is False
    assert any("77" in opt or "7" in opt for opt in status_7777["nearest_options"])


def test_station_bus_routes_intent_and_multi_stop_selection():
    """
    Verify requirement:
    - User searches for: "What bus routes server dubbo train station"
    - Multiple transit stops with matching numbers/names are returned
    - User can select multiple stops (multi_select is True)
    """
    clarifier = IntentClarifier("data/lake/nsw_route_lookup_index.json")

    # 1. Test "What bus routes server dubbo train station" (including user typo "server")
    for q in [
        "What bus routes server dubbo train station",
        "What bus routes serve dubbo train station",
        "bus routes at dubbo station"
    ]:
        res = clarifier.analyze_intent(q)
        assert res["query_type"] == "station_routes", f"Failed to identify station_routes for query: {q}"
        assert res["target_station"] == "Dubbo"
        assert len(res["clarifications_needed"]) == 1
        clarif = res["clarifications_needed"][0]
        assert clarif["parameter"] == "transit_stops"
        assert clarif["multi_select"] is True, "multi_select MUST be True when multiple transit stops exist"
        assert len(clarif["stops_data"]) >= 5, "Expected multiple transit stops (Coach Bays, Platforms) at Dubbo Station"
        
        # Verify Coach Bays and Platform 1 are present with stop codes
        stop_names = [s["name"] for s in clarif["stops_data"]]
        assert any("Coach Bay" in n for n in stop_names), f"Coach bays missing in {stop_names}"
        assert any("Platform" in n or "Talbragar" in n for n in stop_names)


def test_dubbo_station_routes_lakehouse_query_execution():
    """
    Verify requirement:
    - User executes query for Dubbo train station stops
    - GCS lakehouse query returns all bus routes serving the station and all timetable schedules
    """
    engine = GcsQueryEngine()
    stop_ids = ['28302', '2830203', '2830204', '2830205', '2830143', '28301142', '28301261']
    sql = engine.build_station_routes_sql(stop_ids)

    assert "SELECT DISTINCT" in sql
    assert "routes r" in sql
    assert "stop_times st" in sql
    assert "28302" in sql

    df = engine.execute_query(sql)
    assert not df.empty, "Dubbo station query must return non-empty schedules from lakehouse"
    
    # Verify schedules count and distinct bus routes
    assert len(df) >= 50, f"Expected >= 50 scheduled trips at Dubbo Station, got {len(df)}"
    routes = df["route_short_name"].unique()
    assert len(routes) >= 15, f"Expected >= 15 distinct bus routes serving Dubbo Station, got {len(routes)}"
    
    # Specific known Dubbo bus routes
    assert "555" in routes, "Route 555 (Narromine) should serve Dubbo Station"
    assert "556" in routes, "Route 556 (Wellington) should serve Dubbo Station"
    assert "572" in routes, "Route 572 (Orana Mall Loop) should serve Dubbo Station"
    assert "361" in routes or "362" in routes, "Tamworth routes should serve Dubbo Coach Terminal"


def test_dubbo_route_geometries_present_for_map():
    """
    Verify requirement:
    - User sees all the bus routes on the map
    - All routes serving Dubbo Station have genuine road network geometry
    """
    import json
    with open("data/lake/nsw_active_route_geometries.json", "r", encoding="utf-8") as f:
        active_geoms = json.load(f)
    
    by_short = active_geoms.get("by_short_name", {})
    # Core Dubbo routes
    for r in ["555", "556", "572", "361", "362", "511", "512", "513", "514", "516", "523", "524", "569", "570", "589", "590", "791", "792"]:
        assert r in by_short, f"Route {r} geometry missing in active_route_geometries"
        geom = by_short[r][0].get("route_geometry", [])
        assert len(geom) >= 2, f"Route {r} must have physical road geometry points"

    # Verify scenario in nsw_timetable_optimizations.json
    with open("data/lake/nsw_timetable_optimizations.json", "r", encoding="utf-8") as f:
        opts = json.load(f)

    assert "dubbo_train_station" in opts
    sc = opts["dubbo_train_station"]
    assert len(sc["stops"]) >= 5
    assert len(sc["map"]["multi_routes"]) >= 15
    assert len(sc["recommendations"]) >= 50


def test_taree_corridor_bus_routes_and_geometries():
    """
    Verify requirements for query: 'busses from Tarree'
    1. Handles spelling typos ('busses' vs 'buses', 'Tarree' vs 'Taree')
    2. Retrieves multiple active passenger bus routes operating in Taree
    3. Guarantees genuine road centerline alignments in active geometries
    """
    import json
    clarifier = IntentClarifier()
    stations = clarifier.extract_station_hints("busses from Tarree")
    assert "Taree" in stations, "Taree should be extracted as station hint from 'busses from Tarree'"

    # Verify routes in route lookup index
    with open("data/lake/nsw_route_lookup_index.json", "r", encoding="utf-8") as f:
        route_index = json.load(f)

    taree_routes = []
    for k, item in route_index.items():
        for c in item.get("corridors", []):
            if "taree" in c.get("route_long_name", "").lower():
                taree_routes.append(item["route_short_name"])
                break

    assert len(taree_routes) >= 10, f"Expected at least 10 Taree bus routes, found {len(taree_routes)}"
    for core_r in ["310", "316", "320", "319", "311", "312", "313", "314", "150"]:
        assert core_r in taree_routes, f"Core Taree bus route {core_r} should be present"

    # Verify road network centerlines in active geometries
    with open("data/lake/nsw_active_route_geometries.json", "r", encoding="utf-8") as f:
        active_geoms = json.load(f)

    by_short = active_geoms.get("by_short_name", {})
    for core_r in ["310", "316", "320", "319", "311", "312", "313", "314", "150", "154", "309", "135", "136"]:
        assert core_r in by_short, f"Route {core_r} must be in active route geometries"
        geom = by_short[core_r][0].get("route_geometry", [])
        assert len(geom) >= 2, f"Route {core_r} must have authentic road geometry coordinates"


def test_taree_lakehouse_multi_bus_sql_query():
    """
    Verify DuckDB query against lakehouse Parquet tables for multiple Taree bus routes.
    """
    import duckdb
    con = duckdb.connect()
    
    # Query trips for multiple selected Taree routes
    selected_routes = ["310", "316", "320", "319", "150"]
    route_list_str = ", ".join(f"'{r}'" for r in selected_routes)
    
    query = f"""
    SELECT DISTINCT
        r.route_short_name,
        r.route_long_name,
        t.trip_id,
        t.trip_headsign
    FROM 'data/lake/nsw_routes.parquet' r
    JOIN 'data/lake/nsw_trips.parquet' t ON r.route_id = t.route_id
    WHERE r.route_short_name IN ({route_list_str})
    ORDER BY r.route_short_name
    """
    df = con.execute(query).df()
    assert len(df) > 0, "Query should return scheduled trips for selected Taree bus routes"
    retrieved_routes = set(df["route_short_name"].unique())
    assert len(retrieved_routes) >= 4, "Should return trips across multiple selected routes"




