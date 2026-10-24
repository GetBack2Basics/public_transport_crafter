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
