"""Domain constants — loaded from config/base.yaml globals section.

All constants are defined in YAML (config/base.yaml → globals:).
This module loads them at import time so existing imports continue to work.

To change any constant: edit config/base.yaml, not this file.

TODO(DIP): Dependency Inversion Violation
----------------------------------------
This module directly loads from config/base.yaml via yaml.safe_load(),
violating dependency inversion. The domain layer should receive configuration
through injected ports (IConfig/IGlobals), not load infrastructure files.

Proper fix would require:
1. Application layer to load YAML and create a IGlobals implementation
2. Domain services to receive IGlobals via constructor injection
3. This file to become a thin wrapper that receives injected config

This refactoring is deferred due to deep coupling across the codebase.
The ports infrastructure is now in place: app.domain.ports.config_port
"""

import os
import logging

logger = logging.getLogger(__name__)


def _load_globals() -> dict:
    """Load globals section from config/base.yaml."""
    try:
        import yaml

        config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        base_path = os.path.join(config_dir, "base.yaml")
        if os.path.isfile(base_path):
            with open(base_path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("globals", {})
    except Exception as e:
        logger.debug("Could not load globals from base.yaml: %s", e)
    return {}


_G = _load_globals()

# ============================================================================
# Volume Profile (FR-02)
# ============================================================================
LVN_THRESHOLD = _G.get("lvn_threshold", 0.15)  # legacy — kept for compatibility
HVN_THRESHOLD = _G.get("hvn_threshold", 2.00)   # legacy — kept for compatibility
VALUE_AREA_PCT = _G.get("value_area_pct", 0.70)
LVN_SMOOTHING = _G.get("lvn_smoothing", 3)
LVN_MIN_PERSISTENCE_BARS = _G.get("lvn_min_persistence_bars", 1)   # was 2
LVN_REMOVAL_THRESHOLD = _G.get("lvn_removal_threshold", 0.50)
# Percentile-based detection thresholds (Bug #1 fix)
LVN_PERCENTILE = _G.get("lvn_percentile", 20.0)   # bottom 20% = LVN candidate (was 15.0 — too strict)
HVN_PERCENTILE = _G.get("hvn_percentile", 85.0)   # was 75.0 — top 15% = HVN candidate
# Minimum price separation between distinct nodes — prevents dense clusters (Bug #2 fix)
# Default = 3 tick steps for crude oil option profiles; callers should pass tick_size * 3 at runtime.
LVN_MIN_SEPARATION = _G.get("lvn_min_separation", 3.0)   # cluster within 3 points (was 5.0 — over-clustering)
HVN_MIN_SEPARATION = _G.get("hvn_min_separation", 5.0)   # was 3.0 — cluster within 5 points
DELTA_BUCKET_SIZE_DEFAULT = _G.get("delta_bucket_size_default", 0.05)
DELTA_PROFILE_BUCKETS = _G.get("delta_profile_buckets", 200)

# ============================================================================
# Order Flow Metrics (FR-03)
# ============================================================================
CVD_SLOPE_WINDOW = _G.get("cvd_slope_window", 20)
CVD_STRONG_SLOPE = _G.get("cvd_strong_slope", 2.0)
CVD_SLOPE_HARD_BLOCK = _G.get("cvd_slope_hard_block", 50.0)
CVD_SLOPE_WARNING = _G.get("cvd_slope_warning", 30.0)
CVD_SLOPE_EXTREME = _G.get("cvd_slope_extreme", 100.0)
CVD_SLOPE_PERSISTENCE_BARS = _G.get("cvd_slope_persistence_bars", 3)
CVD_SLOPE_EXTENDED_WINDOW = _G.get("cvd_slope_extended_window", 40)
CVD_BLOCK_THRESHOLD_NSE = _G.get("cvd_block_threshold_nse", 5000)
CVD_BLOCK_THRESHOLD_MCX = _G.get("cvd_block_threshold_mcx", 50)

# ── Entry Gate Thresholds ─────────────────────────────────────────
D2_CVD_SLOPE_MAX: float = 80.0  # Max CVD slope for D2 entry (widened from 50)

FOOTPRINT_IMBALANCE_RATIO = _G.get("footprint_imbalance_ratio", 3.0)
FOOTPRINT_IMBALANCE_PCT = _G.get("footprint_imbalance_pct", 0.40)
ABSORPTION_RANGE_ATR = _G.get("absorption_range_atr", 0.30)
ABSORPTION_VOL_MULT = _G.get("absorption_vol_mult", 2.0)
BIG_TRADE_MULTIPLIER = _G.get("big_trade_multiplier", 5.0)
BIG_TRADE_CLUSTER_COUNT = _G.get("big_trade_cluster_count", 3)
BIG_TRADE_CLUSTER_TICKS = _G.get("big_trade_cluster_ticks", 2)
VOLUME_BUBBLE_SIGMA = _G.get("volume_bubble_sigma", 2.0)
OFI_WINDOW = _G.get("ofi_window", 10)
DELTA_ZONE_SIGMA_MULT = _G.get("delta_zone_sigma_mult", 2.5)

# ============================================================================
# Market State (FR-04)
# ============================================================================
POC_NO_TRADE_TICKS = _G.get("poc_no_trade_ticks", 2)
BALANCE_RATIO_THRESHOLD = _G.get("balance_ratio_threshold", 0.55)
DRIVE_REJECTION_WICK_RATIO = _G.get("drive_rejection_wick_ratio", 0.5)
DISPLACEMENT_MULTIPLIER = _G.get("displacement_multiplier", 1.5)

# ============================================================================
# Aggression Scoring (FR-06)
# ============================================================================
AGGRESSION_FOOTPRINT = _G.get("aggression_footprint", 1.0)
AGGRESSION_CVD = _G.get("aggression_cvd", 1.0)
AGGRESSION_BIG_TRADE = _G.get("aggression_big_trade", 1.0)
AGGRESSION_ABSORPTION = _G.get("aggression_absorption", 0.5)
AGGRESSION_OFI = _G.get("aggression_ofi", 0.5)
AGGRESSION_CONFLUENCE = _G.get("aggression_confluence", 0.5)
AGGRESSION_BUBBLE = _G.get("aggression_bubble", 0.5)
MIN_AGGRESSION_SCORE = _G.get("min_aggression_score", 2.0)
PYRAMID_AGGRESSION_SCORE = _G.get("pyramid_aggression_score", 3.0)
AGGRESSION_PERSISTENCE_BARS = _G.get("aggression_persistence_bars", 3)
AGGRESSIVE_PRINT_SIGMA = _G.get("aggressive_print_sigma", 2.5)

# ============================================================================
# Structure
# ============================================================================
STRUCTURE_DWELL_TICKS = _G.get("structure_dwell_ticks", 3)
STRUCTURE_COOLDOWN_TICKS = _G.get("structure_cooldown_ticks", 3)
STRUCTURE_CONFIDENCE_GATE = _G.get("structure_confidence_gate", 60)
STRUCTURE_BYPASS_CONFIDENCE = _G.get("structure_bypass_confidence", 70)

# ============================================================================
# Trade Setup (FR-07)
# ============================================================================
MIN_RR_RATIO = _G.get("min_rr_ratio", 1.5)
MAX_CUSHION_TICKS = _G.get("max_cushion_ticks", 10)
SIGNAL_TTL_SECONDS = _G.get("signal_ttl_seconds", 600)
VWAP_EXTREME_MULTIPLIER = _G.get("vwap_extreme_multiplier", 1.01)
DECISION_HISTORY_LIMIT = _G.get("decision_history_limit", 1000)

# ============================================================================
# Risk Management (FR-10)
# ============================================================================
RISK_PER_TRADE_PCT = _G.get("risk_per_trade_pct", 0.005)
MAX_DAILY_LOSS_PCT = _G.get("max_daily_loss_pct", 0.020)
MAX_CONSECUTIVE_LOSSES = _G.get("max_consecutive_losses", 3)
MAX_DRAWDOWN_PCT = _G.get("max_drawdown_pct", 0.030)
ABSOLUTE_CEILING_PCT = _G.get("absolute_ceiling_pct", 0.010)

# ── Account-Level Risk Limits ─────────────────────────────────────
# Hard cap on total cumulative losses across all sessions/symbols.
# This is a NON-OVERRIDABLE circuit breaker per Fabio's AMT strategy spec.
ACCOUNT_MAX_LOSS_ABSOLUTE: float = 30_000.0  # ₹30,000 hard account loss cap

# ============================================================================
# Volume Thresholds
# ============================================================================
VOLUME_IMPULSE_MULTIPLIER = _G.get("volume_impulse_multiplier", 1.5)
VOLUME_AGGRESSION_MULTIPLIER = _G.get("volume_aggression_multiplier", 2.5)

# ============================================================================
# Time
# ============================================================================
WARM_UP_MINUTES_MCX = _G.get("warm_up_minutes_mcx", 15)
WARM_UP_MINUTES_NSE = _G.get("warm_up_minutes_nse", 15)
IB_CANDLES = _G.get("ib_candles", 2)

# ============================================================================
# LLM Throttling
# ============================================================================
LLM_COOLDOWN_SECONDS = _G.get("llm_cooldown_seconds", 10)
STALENESS_TIMEOUT_SECONDS = _G.get("staleness_timeout_seconds", 30)

# ============================================================================
# Grade
# ============================================================================
GRADE_EXTREME_THRESHOLD = _G.get("grade_extreme_threshold", -5)

# ============================================================================
# Data Limits
# ============================================================================
MAX_CANDLES = _G.get("max_candles", 1000)
TICK_BATCH_SIZE = _G.get("tick_batch_size", 50)
TICK_FLUSH_INTERVAL_SECS = _G.get("tick_flush_interval_secs", 5.0)

# ============================================================================
# Engine Throttling (extracted magic numbers)
# ============================================================================
TICK_PROCESS_INTERVAL = _G.get("tick_process_interval", 0.5)       # seconds between full process_tick
NOTIFY_THROTTLE_INTERVAL = _G.get("notify_throttle_interval", 0.15) # seconds between WS notifications

# ============================================================================
# Agent Decision Thresholds
# ============================================================================
# Minimum agent probability to consider taking action (entry/execution)
# Rationale: P >= 0.55 with 2:1 R/R → 37% break-even win rate actual
AGENT_DECISION_THRESHOLD = _G.get("agent_decision_threshold", 0.55)

# Confidence classification thresholds for UI/presentation
# Used to label decisions as HIGH/MEDIUM/LOW conviction
CONFIDENCE_HIGH_THRESHOLD = 0.65  # High conviction (35%+ WR at 2:1 R/R)
CONFIDENCE_LOW_THRESHOLD = 0.50   # Minimum to consider (below AGENT_DECISION_THRESHOLD = reject)

# ============================================================================
# Analysis Parameters
# ============================================================================
IB_MINUTES: int = 10                     # Initial Balance window in minutes
DISPLACEMENT_LOOKBACK: int = 15          # Lookback for leg detection in displacement
RECENT_DATA_WINDOW: int = 100            # Window for recent data calculations
CANDLE_INTERVAL_MINUTES: int = 5         # Candle interval in minutes

# ── Gate Pipeline Configuration ────────────────────────────────────────────
SOFT_GATE_QUORUM: int = _G.get("soft_gate_quorum", 3)  # Minimum soft gates that must pass (Fabio's 3/4 rule)

# ── ATR Trailing Stop ─────────────────────────────────────────────
# Activates after cushioning (partial TP taken). Advances SL by tracking
# peak unrealised profit and trailing at ATR_TRAIL_STEP_PCT behind the peak.
ATR_TRAIL_ACTIVATION_R: float = 1.0      # Activate after 1.0R profit (post-cushioning)
ATR_TRAIL_STEP_PCT: float = 0.20         # Trail 20% behind peak profit
ATR_TRAIL_PERIOD: int = 14               # ATR lookback period (candles)
