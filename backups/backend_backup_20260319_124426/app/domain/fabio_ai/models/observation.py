"""AMTObservation — RL state vector for the Valentini AMT environment.

This lives in the Fabio AI layer since it is consumed exclusively
by the RL environment, trainer, and the AMT analyzer's compute_observation().
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AMTObservation:
    """RL state vector for the Valentini AMT environment.

    All continuous features are normalised to approximately [-1, 1] or [0, 1]
    by the environment wrapper before being fed into the policy network.
    """
    dist_to_poc: float         # Normalised distance to Point of Control
    is_in_balance: bool        # Price inside prior session's VA?
    delta_divergence: float    # Z-score of Price vs CVD divergence
    nearest_lvn: float         # Price level of closest Low Volume Node
    cvd_slope: float           # CVD linear-regression slope
    profile_shape: str         # "D" / "P" / "b"
    poc_migration: str         # "RISING" / "FALLING" / "STABLE"
    session: str               # "LONDON" / "NEW_YORK" / "ASIA" / "OVERLAP"
    opening_relation: str      # "IN_BALANCE" / "OUT_ABOVE" / "OUT_BELOW"
    aggression_sigma: float    # Volume spike in standard-deviation units
    obi: float                 # Order book imbalance [-1, 1]
    norm_delta: float          # Normalised candle delta
