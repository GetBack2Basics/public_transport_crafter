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

        # Verify analytics and AI suggested next steps
        assert "analytics" in sc
        assert "buffer_distribution" in sc["analytics"]
        assert "hourly_frequency" in sc["analytics"]
        assert "performance_metrics" in sc["analytics"]

        assert "ai_suggested_steps" in sc
        assert len(sc["ai_suggested_steps"]) >= 3
        for step in sc["ai_suggested_steps"]:
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


