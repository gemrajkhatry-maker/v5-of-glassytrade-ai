"""AMTObservation — AMT observation state vector."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class AMTObservation:
    """Observation vector for AMT state."""

    # Price Microstructure
    dist_to_poc: float
    is_in_balance: bool
    delta_divergence: float
    nearest_lvn: float
    cvd_slope: float
    profile_shape: str
    poc_migration: str
    session: str
    opening_relation: str
    aggression_sigma: float
    obi: float
    norm_delta: float

    # Order Book
    bid_imbalance: float = 0.0
    depth_imbalance: float = 0.0
    spread_pct: float = 0.0

    # Options-Specific
    pcr_ratio: float = 0.0
    oi_change: float = 0.0
    moneyness: float = 0.0
    iv_rank: float = 0.0

    # Temporal
    session_minute: float = 0.0
    minutes_to_expiry: float = 0.0
    day_of_week: float = 0.0

    # AMT Context
    drive_state: str = ""
    absorption_side: str = ""
    gap_fill_probability: float = 0.0
    opening_type: str = ""
    tf_alignment: str = ""
