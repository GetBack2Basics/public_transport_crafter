"""
tests/test_optimizer.py
Tests Zero-Resource constraint programming & timetable solver.
Asserts fleet PVR invariance, duty hour conservation, headway regularity, and friction reduction.
"""

import pytest
import pandas as pd
from src.Analysis.optimizer import ZeroResourceTimetableOptimizer, time_str_to_minutes
from src.Analysis.transfer_friction_model import calculate_single_transfer_penalty


def test_transfer_friction_penalty_curve():
    """Validates piecewise penalty function: 0 penalty in 4-8m window, quadratic >8m, heavy <4m."""
    assert calculate_single_transfer_penalty(6.0) == 0.0
    assert calculate_single_transfer_penalty(4.0) == 0.0
    assert calculate_single_transfer_penalty(8.0) == 0.0

    # Wait > 8 min
    assert calculate_single_transfer_penalty(10.0) == (10.0 - 8.0) ** 2  # 4.0
    assert calculate_single_transfer_penalty(14.0) == (14.0 - 8.0) ** 2  # 36.0

    # Missed / tight connection (< 4 min)
    assert calculate_single_transfer_penalty(2.0) > 10000.0


def test_optimizer_strictly_enforces_zero_resource_constraints():
    """
    Asserts:
      1. Peak Vehicle Requirement (PVR) is not increased
      2. Driver duty hours are not increased
      3. Minimum headway (12 min) is preserved
      4. Transfer wait time is substantially improved
    """
    optimizer = ZeroResourceTimetableOptimizer(
        max_shift_minutes=15,
        min_headway_minutes=12,
        trip_duration_minutes=35
    )

    # Trunk train arrivals at interchange (e.g. Hamilton Station)
    trunk_arrivals = ["06:40:00", "07:10:00", "07:40:00", "08:10:00", "08:40:00"]

    # Baseline feeder departures with poor sync (e.g. bus departing 2 min BEFORE train or 25 min after)
    baseline_feeder = ["06:38:00", "07:05:00", "07:38:00", "08:05:00", "08:38:00"]
    feeder_ids = [f"FEEDER_{i+1:02d}" for i in range(len(baseline_feeder))]

    results = optimizer.solve(
        trunk_arrival_times=trunk_arrivals,
        baseline_feeder_departures=baseline_feeder,
        feeder_trip_ids=feeder_ids
    )

    base_m = results["baseline_metrics"]
    opt_m = results["optimized_metrics"]
    delta_m = results["resource_delta"]

    # Constraint 1: PVR must not exceed baseline
    assert opt_m["peak_vehicle_requirement"] <= base_m["peak_vehicle_requirement"], (
        f"Fleet PVR violated! Opt: {opt_m['peak_vehicle_requirement']} > Base: {base_m['peak_vehicle_requirement']}"
    )

    # Constraint 2: Duty hours must not exceed baseline
    assert opt_m["duty_hours"] <= base_m["duty_hours"], "Duty hours constraint exceeded!"

    # Constraint 3: Additional cost must be zero
    assert delta_m["additional_budget_aud"] == 0.00

    # Constraint 4: Headway between consecutive trips must be >= min_headway
    opt_trips = results["optimized_trips_df"]
    opt_dept_mins = [time_str_to_minutes(t) for t in opt_trips["optimized_departure"]]
    for i in range(len(opt_dept_mins) - 1):
        gap = opt_dept_mins[i + 1] - opt_dept_mins[i]
        assert gap >= optimizer.min_headway, f"Headway violation between trip {i} and {i+1}: {gap}m < {optimizer.min_headway}m"

    # Outcome: Average wait time and friction penalty must be improved
    assert opt_m["avg_wait_minutes"] <= base_m["avg_wait_minutes"], "Optimization failed to reduce average wait time"
    assert opt_m["total_penalty"] < base_m["total_penalty"], "Optimization failed to reduce network friction penalty"
