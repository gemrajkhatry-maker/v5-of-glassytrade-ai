"""AMTObservation — RL state vector for the Valentini AMT environment.

This lives in the Fabio AI layer since it is consumed exclusively
by the RL environment, trainer, and the AMT analyzer's compute_observation().

#28: Expanded from 12 to 24+ features:
- Group A: Price Microstructure (6) — existing
- Group B: Order Flow (3) — existing
- Group C: Order Book (3) — NEW: bid_imbalance, depth_imbalance, spread_pct
- Group D: Options-Specific (4) — NEW: pcr_ratio, oi_change, moneyness, iv_rank
- Group E: Temporal (3) — NEW: session_minute, minutes_to_expiry, day_of_week
- Group F: AMT Context (5) — NEW: drive_state, absorption_side, gap_fill_prob,
  opening_type, tf_alignment
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AMTObservation:
    """RL state vector for the Valentini AMT environment.

    All continuous features are normalised to approximately [-1, 1] or [0, 1]
    by the environment wrapper before being fed into the policy network.
    """

    # ── Group A: Price Microstructure ──
    dist_to_poc: float  # Normalised distance to Point of Control
    is_in_balance: bool  # Price inside prior session's VA?
    delta_divergence: float  # Z-score of Price vs CVD divergence
    nearest_lvn: float  # Price level of closest Low Volume Node
    cvd_slope: float  # CVD linear-regression slope
    profile_shape: str  # "D" / "P" / "b"
    poc_migration: str  # "RISING" / "FALLING" / "STABLE"
    session: str  # "LONDON" / "NEW_YORK" / "ASIA" / "OVERLAP"
    opening_relation: str  # "IN_BALANCE" / "OUT_ABOVE" / "OUT_BELOW"
    aggression_sigma: float  # Volume spike in standard-deviation units
    obi: float  # Order book imbalance [-1, 1]
    norm_delta: float  # Normalised candle delta

    # ── Group C: Order Book (NEW) ──
    bid_imbalance: float = 0.0  # Bid depth imbalance [-1, 1]
    depth_imbalance: float = 0.0  # Total depth imbalance [-1, 1]
    spread_pct: float = 0.0  # Bid-ask spread as % of price

    # ── Group D: Options-Specific (NEW) ──
    pcr_ratio: float = 0.0  # Put/Call ratio
    oi_change: float = 0.0  # Open interest change %
    moneyness: float = 0.0  # Strike / Spot ratio (1.0 = ATM)
    iv_rank: float = 0.0  # Implied volatility rank [0, 1]

    # ── Group E: Temporal (NEW) ──
    session_minute: float = 0.0  # Minutes since session open
    minutes_to_expiry: float = 0.0  # Minutes to options expiry
    day_of_week: float = 0.0  # 0=Mon, 4=Fri

    # ── Group F: AMT Context (NEW) ──
    drive_state: str = ""  # "FRESH" / "MATURING" / "DECAYING" / "EXHAUSTED"
    absorption_side: str = ""  # "SELL_ABSORBED" / "BUY_ABSORBED" / ""
    gap_fill_probability: float = 0.0  # Gap fill probability [0, 1]
    opening_type: str = ""  # Opening type classification
    tf_alignment: str = (
        ""  # "ALIGNED_LONG" / "ALIGNED_SHORT" / "CONFLICTED" / "NEUTRAL"
    )
