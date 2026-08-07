"""Domain constants — loaded from config/base.yaml globals section.

All constants are defined in YAML (config/base.yaml → globals:).
This module loads them at import time so existing imports continue to work.

To change any constant: edit config/base.yaml, not this file.

NOTE: This module now uses injected configuration via GlobalsImpl.
The infrastructure adapter loads from YAML and provides values to this module.
"""

import logging
import os

logger = logging.getLogger(__name__)


def _load_globals_dict() -> dict:
    """Load globals section from config/base.yaml."""
    try:
        import yaml

        # Moved from backend/app/domain/constants.py — resolve backend/config/base.yaml
        # (now: quant/contracts/../.. = repo root, then backend/config) to keep loading
        # the same YAML globals the backend loaded at its original path.
        config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "config")
        base_path = os.path.join(config_dir, "base.yaml")
        if os.path.isfile(base_path):
            with open(base_path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("globals", {})
    except Exception as e:
        logger.debug("Could not load globals from base.yaml: %s", e)
    return {}


# Load globals once at module level
_globals_dict = _load_globals_dict()


# Helper to get values from globals with defaults
def _get(key: str, default) -> float | int | str:
    """Get a value from the globals config with a default fallback."""
    return _globals_dict.get(key, default)


# ============================================================================
# Volume Profile (FR-02)
# ============================================================================
LVN_THRESHOLD = _get("lvn_threshold", 0.15)
HVN_THRESHOLD = _get("hvn_threshold", 2.00)
VALUE_AREA_PCT = _get("value_area_pct", 0.70)
LVN_SMOOTHING = _get("lvn_smoothing", 3)
LVN_MIN_PERSISTENCE_BARS = _get("lvn_min_persistence_bars", 1)
LVN_REMOVAL_THRESHOLD = _get("lvn_removal_threshold", 0.50)
LVN_PERCENTILE = _get("lvn_percentile", 20.0)
HVN_PERCENTILE = _get("hvn_percentile", 85.0)
LVN_MIN_SEPARATION = _get("lvn_min_separation", 3.0)
HVN_MIN_SEPARATION = _get("hvn_min_separation", 5.0)
DELTA_BUCKET_SIZE_DEFAULT = _get("delta_bucket_size_default", 0.05)
DELTA_PROFILE_BUCKETS = _get("delta_profile_buckets", 200)

# ============================================================================
# Order Flow Metrics (FR-03)
# ============================================================================
CVD_SLOPE_WINDOW = _get("cvd_slope_window", 20)
CVD_STRONG_SLOPE = _get("cvd_strong_slope", 2.0)
CVD_SLOPE_HARD_BLOCK = 50.0
CVD_SLOPE_WARNING = 30.0
CVD_SLOPE_EXTREME = 100.0
CVD_SLOPE_PERSISTENCE_BARS = _get("cvd_slope_persistence_bars", 3)
CVD_SLOPE_EXTENDED_WINDOW = _get("cvd_slope_extended_window", 40)
CVD_BLOCK_THRESHOLD_NSE = 5000
CVD_BLOCK_THRESHOLD_MCX = 50

D2_CVD_SLOPE_MAX: float = 80.0

FOOTPRINT_IMBALANCE_RATIO = _get("footprint_imbalance_ratio", 3.0)
FOOTPRINT_IMBALANCE_PCT = _get("footprint_imbalance_pct", 0.40)
ABSORPTION_RANGE_ATR = _get("absorption_range_atr", 0.30)
ABSORPTION_VOL_MULT = _get("absorption_vol_mult", 2.0)
BIG_TRADE_MULTIPLIER = _get("big_trade_multiplier", 5.0)
BIG_TRADE_CLUSTER_COUNT = _get("big_trade_cluster_count", 3)
BIG_TRADE_CLUSTER_TICKS = _get("big_trade_cluster_ticks", 2)
VOLUME_BUBBLE_SIGMA = _get("volume_bubble_sigma", 2.0)
OFI_WINDOW = _get("ofi_window", 10)
DELTA_ZONE_SIGMA_MULT = _get("delta_zone_sigma_mult", 2.5)

# ============================================================================
# Market State (FR-04)
# ============================================================================
POC_NO_TRADE_TICKS = 2
BALANCE_RATIO_THRESHOLD = _get("balance_ratio_threshold", 0.55)
DRIVE_REJECTION_WICK_RATIO = _get("drive_rejection_wick_ratio", 0.5)
DISPLACEMENT_MULTIPLIER = _get("displacement_multiplier", 1.5)

# ============================================================================
# Aggression Scoring (FR-06)
# ============================================================================
AGGRESSION_FOOTPRINT = 1.0
AGGRESSION_CVD = 1.0
AGGRESSION_BIG_TRADE = 1.0
AGGRESSION_ABSORPTION = 0.5
AGGRESSION_OFI = 0.5
AGGRESSION_CONFLUENCE = 0.5
AGGRESSION_BUBBLE = 0.5
MIN_AGGRESSION_SCORE = _get("min_aggression_score", 2.0)
PYRAMID_AGGRESSION_SCORE = _get("pyramid_aggression_score", 3.0)
AGGRESSION_PERSISTENCE_BARS = _get("aggression_persistence_bars", 3)
AGGRESSIVE_PRINT_SIGMA = _get("aggressive_print_sigma", 2.5)

# ============================================================================
# Structure
# ============================================================================
STRUCTURE_DWELL_TICKS = 3
STRUCTURE_COOLDOWN_TICKS = 3
STRUCTURE_CONFIDENCE_GATE = 60
STRUCTURE_BYPASS_CONFIDENCE = 70

# ============================================================================
# Trade Setup (FR-07)
# ============================================================================
MIN_RR_RATIO = 1.5
MAX_CUSHION_TICKS = 10
# 60s scalar-session default; runtime override via SIGNAL_STALE_SECONDS setting
SIGNAL_TTL_SECONDS = 60
VWAP_EXTREME_MULTIPLIER = 1.01
DECISION_HISTORY_LIMIT = 1000

# ============================================================================
# Risk Management (FR-10)
# ============================================================================
RISK_PER_TRADE_PCT = _get("risk_per_trade_pct", 0.005)
MAX_DAILY_LOSS_PCT = _get("max_daily_loss_pct", 0.020)
MAX_CONSECUTIVE_LOSSES = _get("max_consecutive_losses", 3)
MAX_DRAWDOWN_PCT = 0.030
ABSOLUTE_CEILING_PCT = 0.010

ACCOUNT_MAX_LOSS_ABSOLUTE: float = 30_000.0

# ============================================================================
# Volume Thresholds
# ============================================================================
VOLUME_IMPULSE_MULTIPLIER = 1.5
VOLUME_AGGRESSION_MULTIPLIER = 2.5

# ============================================================================
# Time
# ============================================================================
WARM_UP_MINUTES_MCX = 15
WARM_UP_MINUTES_NSE = 15
IB_CANDLES = 2

# ============================================================================
# LLM Throttling
# ============================================================================
LLM_COOLDOWN_SECONDS = 10
STALENESS_TIMEOUT_SECONDS = 30

# ============================================================================
# Grade
# ============================================================================
GRADE_EXTREME_THRESHOLD = -5

# ============================================================================
# Data Limits
# ============================================================================
MAX_CANDLES = 1000
TICK_BATCH_SIZE = 50
TICK_FLUSH_INTERVAL_SECS = 5.0

# ============================================================================
# Engine Throttling (extracted magic numbers)
# ============================================================================
TICK_PROCESS_INTERVAL = 0.5
NOTIFY_THROTTLE_INTERVAL = 0.15

# ============================================================================
# Agent Decision Thresholds
# ============================================================================
AGENT_DECISION_THRESHOLD = _get("agent_decision_threshold", 0.55)
CONFIDENCE_HIGH_THRESHOLD = 0.65
CONFIDENCE_LOW_THRESHOLD = 0.50
MIN_GRADE_SCORE_THRESHOLD = 1

# ============================================================================
# Analysis Parameters
# ============================================================================
IB_MINUTES: int = 30
DISPLACEMENT_LOOKBACK: int = 15
RECENT_DATA_WINDOW: int = 100
CANDLE_INTERVAL_MINUTES: int = 5

SOFT_GATE_QUORUM: int = 3

# ── ATR Trailing Stop ─────────────────────────────────────────────
ATR_TRAIL_ACTIVATION_R: float = 1.0
ATR_TRAIL_STEP_PCT: float = 0.20
ATR_TRAIL_PERIOD: int = 14