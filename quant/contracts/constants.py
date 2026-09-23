"""Domain constants — loaded from config/base.yaml globals section.

All constants are defined in YAML (config/base.yaml → globals:).
This module loads them at import time so existing imports continue to work.

To change any constant: edit config/base.yaml, not this file.

NOTE: This module now uses injected configuration via GlobalsImpl.
The infrastructure adapter loads from YAML and provides values to this module.
"""

import logging
import os

from quant.contracts.aggregates import INITIAL_CAPITAL as _INITIAL_CAPITAL

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
# Fabio AMT spec §5.1 rule 4: LVN = { p | V(p) < 0.35 x V_bar_profile AND
# d^2V(p)/dp^2 > 0 }. The review's C6 finding measured that the operative gate
# was a 20th-PERCENTILE rank with no absolute floor: a percentile shifts with
# the distribution's shape, and on the right-skewed profiles order flow
# actually produces, the 20th percentile exceeded 0.35 x mean in 3,000/3,000
# generated cases — so the code admitted troughs the spec rejects. The
# absolute floor now gates alongside the percentile (the stricter binds), and
# the dead LVN_THRESHOLD/HVN_THRESHOLD (documented "kept for API compatibility
# (unused)") are retained only as aliases so nothing imports a vanished name.
LVN_VOL_FRACTION = _get("lvn_vol_fraction", 0.35)
LVN_THRESHOLD = _get("lvn_threshold", 0.15)
HVN_THRESHOLD = _get("hvn_threshold", 2.00)
# Fabio AMT spec §5.1 rule 3: "Value Area (VA = 68.2% of Total Volume)".
# This is the boundary that classifies the whole market (BALANCED vs IMBALANCED),
# so a wider VA silently reclassifies imbalanced conditions as balanced. Do not
# "round" it to 0.70: the spec states 0.682, and the resulting VA edges feed
# every acceptance/rejection/target level in Playbooks A and B.
VALUE_AREA_PCT = _get("value_area_pct", 0.682)
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
# Fabio AMT spec §7.2 rule 1-2. Two corrections vs the pre-remediation values
# (2.0 / 0.30-ATR), which the spec does not contain:
#   * volume: 1.50x the 20-BAR rolling mean, not 2.0x the full-window mean;
#   * range:  <= 0.50 x H_range (the 20-bar average RANGE), not 0.30 x ATR.
# ATR and average range differ (ATR accounts for gaps), so the old denominator
# was both the wrong number and the wrong statistic. Both are load-bearing:
# this predicate feeds Triple-A ACCUMULATION and the pyramid authorisation floor.
ABSORPTION_RANGE_RATIO_MAX = _get("absorption_range_ratio_max", 0.50)
ABSORPTION_VOL_MULT = _get("absorption_vol_mult", 1.50)
# Legacy aliases kept for the test pins that still import the old names;
# they resolve to the spec values so no caller silently keeps 0.30/2.0.
# (v7 N6 reference check: no production reader remains for any of the three.)
ABSORPTION_RANGE_ATR = ABSORPTION_RANGE_RATIO_MAX
FABIO_ABSORPTION_RANGE_ATR: float = ABSORPTION_RANGE_RATIO_MAX
FABIO_ABSORPTION_VOL_MULT: float = ABSORPTION_VOL_MULT
BIG_TRADE_MULTIPLIER = _get("big_trade_multiplier", 5.0)
BIG_TRADE_CLUSTER_COUNT = _get("big_trade_cluster_count", 3)
BIG_TRADE_CLUSTER_TICKS = _get("big_trade_cluster_ticks", 2)
VOLUME_BUBBLE_SIGMA = _get("volume_bubble_sigma", 2.0)
OFI_WINDOW = _get("ofi_window", 10)
DELTA_ZONE_SIGMA_MULT = _get("delta_zone_sigma_mult", 2.5)

# ============================================================================
# Market State (FR-04)
# ============================================================================
POC_NO_TRADE_TICKS = int(_get("poc_no_trade_ticks", 2))
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
MAX_STOP_DISTANCE_TICKS = 200.0
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
# Engine / Runtime (v7 N6: folded in from the deleted quant/config/constants.py
# so the repo has exactly ONE constants module)
# ============================================================================
WARMUP_BARS = 15
CVD_KILL_THRESHOLD = 2.0
JSONL_FLUSH_BATCH = 128
DEFAULT_RING_SIZE = 8_192
TICK_SIZE_NSE_OPTIONS = 0.05
SEED_CACHE_TTL_SECONDS = 300
DEFAULT_TIME_STOP_BARS = 60
ABSORPTION_MAX_AGE_BARS = 5
OBI_AGGRESSION_THRESHOLD = 0.20

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
# Canonical sizing literals (D-28)
# ============================================================================
# Equity fallback when a DecisionContext carries none. Must be the ONE
# canonical capital, never a local literal: the scanner used 100000 and the
# snapshot client 200000 while INITIAL_CAPITAL is 1000000 — three different
# numbers for one concept, all on the sizing path.
FALLBACK_EQUITY: float = float(_INITIAL_CAPITAL)

# Notional leverage bound applied in TimesFM dynamic sizing. Named so the
# 2.5x / 3.0x pair cannot drift apart between readers.
MAX_NOTIONAL_LEVERAGE: float = 2.5
NOTIONAL_LEVERAGE_GUARD: float = 3.0

# ============================================================================
# Analysis Parameters
# ============================================================================
# Fabio's framework: the Initial Balance is the high/low of the FIRST HOUR.
# It freezes after 60 minutes (structural day-type reference); the session
# Value Area keeps developing all session. Matches get_ib_window() in
# quant/amt/session/context.py (NSE 09:15-10:15, MCX 09:00-10:00).
IB_MINUTES: int = 60
DISPLACEMENT_LOOKBACK: int = 15
RECENT_DATA_WINDOW: int = 100
CANDLE_INTERVAL_MINUTES: int = 5
# Value area lookback: the VA used for decisions is clamped to the traded
# range of the last N candles so a stale intraday regime (e.g. an option
# premium that collapsed 195 -> 102) cannot inflate VAH/VAL.
RECENT_VA_LOOKBACK: int = 60

SOFT_GATE_QUORUM: int = 3

# ── ATR Trailing Stop ─────────────────────────────────────────────
ATR_TRAIL_ACTIVATION_R: float = 1.0
ATR_TRAIL_STEP_PCT: float = 0.20
ATR_TRAIL_PERIOD: int = 14

# ============================================================================
# Fabio AMT Methodology Parameters
# ============================================================================
# ponytail: Fabio Valentini's AMT methodology thresholds
# Source: https://blog.pickmytrade.trade/fabio-valentini-pro-scalper-nasdaq-scalping-strategy/

# Direction resolution (context_builder.py)
FABIO_CVD_THRESHOLD_NSE: float = 0.5     # CVD slope threshold for NSE
FABIO_CVD_THRESHOLD_MCX: float = 0.3     # CVD slope threshold for MCX
FABIO_OBI_THRESHOLD: float = 0.20        # Order Book Imbalance threshold
FABIO_OFI_THRESHOLD: float = 0.10        # Order Flow Imbalance threshold

# Absorption detection: the FABIO_ABSORPTION_* aliases are defined
# alongside ABSORPTION_* above and now carry the spec §7.2 values.

# Volume Profile
# FABIO_VALUE_AREA_PCT was removed (review C5): it duplicated VALUE_AREA_PCT
# with a different value (0.70 vs the spec's 0.682) and was consumed only by a
# test. There is now one VA constant, and it is the spec's number.