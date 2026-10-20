#!/usr/bin/env python3
"""
src/Analysis/transfer_friction_model.py
Evaluates transfer buffer windows, connection friction penalties, and Opal passenger flow weighting.
Goal: Incentivize the 4-8 minute sweet spot for high-comfort, low-friction transfers.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple


def calculate_single_transfer_penalty(wait_time_minutes: float) -> float:
    """
    Evaluates the piecewise transfer friction penalty:
      - Optimal (4 <= t <= 8 min): Penalty = 0
      - Excessive wait (t > 8 min): Penalty = (t - 8)^2
      - Missed / Tight connection (t < 4 min): Penalty = 10,000 + 100 * (4 - t)
    """
    if 4.0 <= wait_time_minutes <= 8.0:
        return 0.0
    elif wait_time_minutes > 8.0:
        return float((wait_time_minutes - 8.0) ** 2)
    else:
        # Missed or risk of missing connection due to minor variance
        return float(10000.0 + 100.0 * (4.0 - wait_time_minutes))


def evaluate_transfer_table(transfers_df: pd.DataFrame, opal_weights: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Evaluates an entire table of transfers, computing metrics and passenger-weighted penalties.
    """
    if transfers_df.empty:
        return {
            "total_transfers": 0,
            "avg_wait_minutes": 0.0,
            "pct_optimal_window": 0.0,
            "pct_excessive_wait": 0.0,
            "pct_missed": 0.0,
            "total_penalty": 0.0
        }

    wait_times = transfers_df["wait_time_minutes"].values
    penalties = [calculate_single_transfer_penalty(w) for w in wait_times]
    
    # Apply passenger weighting if provided
    weights = np.ones(len(transfers_df))
    if opal_weights:
        weights = np.array([opal_weights.get(row.get("interchange_stop_id", ""), 1.0) for _, row in transfers_df.iterrows()])

    weighted_penalties = np.array(penalties) * weights
    total_penalty = float(np.sum(weighted_penalties))

    total = len(wait_times)
    optimal_count = int(np.sum((wait_times >= 4.0) & (wait_times <= 8.0)))
    excessive_count = int(np.sum(wait_times > 15.0))
    missed_count = int(np.sum(wait_times < 4.0))

    return {
        "total_transfers": total,
        "avg_wait_minutes": round(float(np.mean(wait_times)), 2),
        "median_wait_minutes": round(float(np.median(wait_times)), 2),
        "pct_optimal_window": round((optimal_count / total) * 100.0, 1),
        "pct_excessive_wait": round((excessive_count / total) * 100.0, 1),
        "pct_missed": round((missed_count / total) * 100.0, 1),
        "total_penalty": round(total_penalty, 2),
        "penalties": penalties
    }
