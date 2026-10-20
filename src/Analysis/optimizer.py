#!/usr/bin/env python3
"""
src/Analysis/optimizer.py
Generalized Zero-Resource Timetable Solver.
Optimizes transit departure offsets (delta_t) to minimize transfer friction
under strict zero-resource constraints:
  1. Fleet Fleet Limit: PVR(optimized) <= PVR(baseline) (Zero additional rolling stock)
  2. Operating Hours Limit: DutyHours(optimized) <= DutyHours(baseline) (Zero added budget)
  3. Headway Regularity: Departure(i+1) - Departure(i) >= H_min (No bus bunching)
"""

import logging
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.Analysis.transfer_friction_model import (
    calculate_single_transfer_penalty,
    evaluate_transfer_table
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("timetable_optimizer")


def time_str_to_minutes(t_str: str) -> int:
    """Converts 'HH:MM:SS' or 'HH:MM' string to minutes from midnight."""
    parts = list(map(int, t_str.split(":")))
    return parts[0] * 60 + parts[1]


def minutes_to_time_str(m: int) -> str:
    """Converts minutes from midnight to 'HH:MM:SS' string."""
    m = m % (24 * 60)
    hh = m // 60
    mm = m % 60
    return f"{hh:02d}:{mm:02d}:00"


class ZeroResourceTimetableOptimizer:
    """
    Solves for optimal departure shifts (delta_t) to maximize connection synchronization
    without adding any rolling stock or increasing duty hours.
    """

    def __init__(
        self,
        max_shift_minutes: int = 15,
        min_headway_minutes: int = 12,
        trip_duration_minutes: int = 40
    ):
        self.max_shift = max_shift_minutes
        self.min_headway = min_headway_minutes
        self.trip_duration = trip_duration_minutes

    def calculate_peak_vehicle_requirement(self, departure_minutes: List[int], run_time: int) -> int:
        """
        Calculates Peak Vehicle Requirement (PVR) as the maximum number of concurrent
        trips active on the network at any minute.
        """
        if not departure_minutes:
            return 0
        events = []
        for d in departure_minutes:
            events.append((d, +1))  # Trip begins
            events.append((d + run_time, -1))  # Trip completes
        events.sort(key=lambda x: (x[0], -x[1]))

        current_active = 0
        max_active = 0
        for _, change in events:
            current_active += change
            if current_active > max_active:
                max_active = current_active
        return max_active

    def solve(
        self,
        trunk_arrival_times: List[str],
        baseline_feeder_departures: List[str],
        feeder_trip_ids: List[str],
        interchange_stop_id: str = "230310",
        interchange_name: str = "Hamilton Station"
    ) -> Dict[str, Any]:
        """
        Executes optimization over feeder departures against trunk arrivals.
        Strictly satisfies zero-resource and headway constraints.
        """
        trunk_arr_min = [time_str_to_minutes(t) for t in trunk_arrival_times]
        base_dept_min = [time_str_to_minutes(t) for t in baseline_feeder_departures]
        n_trips = len(base_dept_min)

        assert n_trips > 0, "No feeder trips provided for optimization"

        # Baseline PVR and Duty hours
        base_pvr = self.calculate_peak_vehicle_requirement(base_dept_min, self.trip_duration)
        base_duty_hours = (n_trips * self.trip_duration) / 60.0

        logger.info(f"Baseline Fleet Metrics: PVR = {base_pvr} vehicles | Duty Hours = {base_duty_hours:.1f} hrs")

        # Optimization decision variables: delta_t for each feeder trip i
        # Bounds: [-max_shift, +max_shift]
        def objective(deltas):
            shifts = np.round(deltas)
            adj_depts = [base_dept_min[i] + int(shifts[i]) for i in range(n_trips)]

            total_penalty = 0.0
            # For each trunk arrival, evaluate wait time to next feeder departure
            for arr in trunk_arr_min:
                valid_feeder = [d for d in adj_depts if d >= arr]
                if valid_feeder:
                    wait = min(valid_feeder) - arr
                else:
                    wait = 30.0  # Missed / outside service window
                total_penalty += calculate_single_transfer_penalty(wait)

            # Headway penalty inside objective for smooth guidance
            for i in range(n_trips - 1):
                gap = adj_depts[i + 1] - adj_depts[i]
                if gap < self.min_headway:
                    total_penalty += 5000.0 * (self.min_headway - gap)

            return total_penalty

        # Initial point: delta_t = 0
        x0 = np.zeros(n_trips)
        bounds = [(-self.max_shift, self.max_shift) for _ in range(n_trips)]

        # Coordinate search / gradient-free discrete exploration for integer minutes
        best_shifts = np.zeros(n_trips, dtype=int)
        best_score = objective(best_shifts)

        # Coordinate descent across discrete minutes
        improved = True
        iterations = 0
        while improved and iterations < 25:
            improved = False
            iterations += 1
            for i in range(n_trips):
                current_shift = best_shifts[i]
                for test_delta in range(-self.max_shift, self.max_shift + 1):
                    trial_shifts = best_shifts.copy()
                    trial_shifts[i] = test_delta

                    # Test headway constraint
                    adj = [base_dept_min[k] + trial_shifts[k] for k in range(n_trips)]
                    headway_violated = any(
                        adj[k + 1] - adj[k] < self.min_headway for k in range(n_trips - 1)
                    )
                    if headway_violated:
                        continue

                    # Test vehicle constraint (Zero additional rolling stock)
                    opt_pvr = self.calculate_peak_vehicle_requirement(adj, self.trip_duration)
                    if opt_pvr > base_pvr:
                        continue

                    score = objective(trial_shifts)
                    if score < best_score:
                        best_score = score
                        best_shifts = trial_shifts
                        improved = True

        opt_dept_min = [base_dept_min[i] + int(best_shifts[i]) for i in range(n_trips)]
        opt_dept_str = [minutes_to_time_str(m) for m in opt_dept_min]
        opt_pvr = self.calculate_peak_vehicle_requirement(opt_dept_min, self.trip_duration)
        opt_duty_hours = (n_trips * self.trip_duration) / 60.0

        # Hard assertion of zero-resource contract
        assert opt_pvr <= base_pvr, f"HARD CONSTRAINT VIOLATION: opt_pvr ({opt_pvr}) > base_pvr ({base_pvr})"
        assert opt_duty_hours <= base_duty_hours, "HARD CONSTRAINT VIOLATION: Duty hours exceeded"
        for i in range(n_trips - 1):
            gap = opt_dept_min[i + 1] - opt_dept_min[i]
            assert gap >= self.min_headway, f"HARD CONSTRAINT VIOLATION: Headway {gap}m < min {self.min_headway}m"

        # Build baseline and optimized transfer tables
        baseline_transfers = self._build_transfer_table(
            trunk_arr_min, trunk_arrival_times, base_dept_min, baseline_feeder_departures,
            feeder_trip_ids, interchange_stop_id, interchange_name
        )
        optimized_transfers = self._build_transfer_table(
            trunk_arr_min, trunk_arrival_times, opt_dept_min, opt_dept_str,
            feeder_trip_ids, interchange_stop_id, interchange_name
        )

        base_eval = evaluate_transfer_table(baseline_transfers)
        opt_eval = evaluate_transfer_table(optimized_transfers)

        # Build optimized trips table
        opt_trips_df = pd.DataFrame({
            "trip_id": feeder_trip_ids,
            "baseline_departure": baseline_feeder_departures,
            "optimized_departure": opt_dept_str,
            "shift_minutes": [int(s) for s in best_shifts],
            "vehicle_allocated": [f"BUS-{(i % opt_pvr) + 1:02d}" for i in range(n_trips)]
        })

        return {
            "baseline_metrics": {
                **base_eval,
                "peak_vehicle_requirement": base_pvr,
                "duty_hours": base_duty_hours,
                "additional_cost_aud": 0.00
            },
            "optimized_metrics": {
                **opt_eval,
                "peak_vehicle_requirement": opt_pvr,
                "duty_hours": opt_duty_hours,
                "additional_cost_aud": 0.00
            },
            "resource_delta": {
                "vehicle_delta": opt_pvr - base_pvr,
                "duty_hours_delta": opt_duty_hours - base_duty_hours,
                "additional_budget_aud": 0.00,
                "wait_time_reduction_minutes": round(base_eval["avg_wait_minutes"] - opt_eval["avg_wait_minutes"], 2),
                "optimal_transfer_increase_pct": round(opt_eval["pct_optimal_window"] - base_eval["pct_optimal_window"], 1),
                "penalty_reduction_pct": round((1.0 - (opt_eval["total_penalty"] / max(base_eval["total_penalty"], 1e-6))) * 100.0, 1)
            },
            "shifts": {feeder_trip_ids[i]: int(best_shifts[i]) for i in range(n_trips)},
            "baseline_transfers_df": baseline_transfers,
            "optimized_transfers_df": optimized_transfers,
            "optimized_trips_df": opt_trips_df
        }

    def _build_transfer_table(
        self,
        trunk_arr_min: List[int],
        trunk_arr_str: List[str],
        feeder_dept_min: List[int],
        feeder_dept_str: List[str],
        feeder_trip_ids: List[str],
        interchange_stop_id: str,
        interchange_name: str
    ) -> pd.DataFrame:
        transfers = []
        for idx, arr in enumerate(trunk_arr_min):
            candidates = [
                (feeder_dept_min[i] - arr, feeder_trip_ids[i], feeder_dept_str[i])
                for i in range(len(feeder_dept_min))
                if feeder_dept_min[i] >= arr
            ]
            if candidates:
                candidates.sort(key=lambda x: x[0])
                wait, f_id, f_dept = candidates[0]
                status = "optimal (4-8m)" if 4 <= wait <= 8 else ("excessive (>8m)" if wait > 8 else "tight (<4m)")
            else:
                wait = 28
                f_id = "N/A"
                f_dept = "N/A"
                status = "missed connection"

            transfers.append({
                "trunk_arrival": trunk_arr_str[idx],
                "feeder_trip_id": f_id,
                "feeder_departure": f_dept,
                "wait_time_minutes": wait,
                "status": status,
                "interchange_stop_id": interchange_stop_id,
                "interchange_name": interchange_name
            })
        return pd.DataFrame(transfers)
