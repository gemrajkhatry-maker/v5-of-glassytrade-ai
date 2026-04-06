"""
Engine configuration — ALL thresholds in one place.

Frozen dataclass ensures no mutation after initialization.
All modules import CFG from this module — no magic numbers elsewhere.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    """All engine thresholds and configuration constants."""

    # =========================================================================
    # VOLUME PROFILE
    # =========================================================================
    value_area_pct: float = 0.70
    lvn_threshold_pct: float = 0.15
    hvn_threshold_pct: float = 2.00
    profile_bucket_size_naturalgas: float = 0.10
    profile_bucket_size_nifty: float = 5.0
    profile_bucket_size_banknifty: float = 5.0

    # =========================================================================
    # CVD (Cumulative Volume Delta)
    # =========================================================================
    cvd_slope_window: int = 20
    cvd_strong_slope: float = 2.0
    cvd_divergence_lookback: int = 10

    # =========================================================================
    # FOOTPRINT
    # =========================================================================
    footprint_imbalance_ratio: float = 3.0
    footprint_imbalance_pct: float = 0.40

    # =========================================================================
    # VOLUME BUBBLE
    # =========================================================================
    volume_bubble_sigma: float = 2.0
    volume_bubble_window: int = 21

    # =========================================================================
    # ABSORPTION
    # =========================================================================
    absorption_range_atr: float = 0.30
    absorption_vol_mult: float = 2.0

    # =========================================================================
    # BIG TRADE
    # =========================================================================
    big_trade_multiplier: float = 5.0
    big_trade_cluster_count: int = 3
    big_trade_cluster_ticks: int = 2

    # =========================================================================
    # OFI (Order Flow Imbalance)
    # =========================================================================
    ofi_window: int = 10
    ofi_long_threshold: float = 0.10
    ofi_short_threshold: float = -0.10

    # =========================================================================
    # VWAP
    # =========================================================================
    vwap_sigma_1: float = 1.0
    vwap_sigma_2: float = 2.0

    # =========================================================================
    # INITIAL BALANCE
    # =========================================================================
    ib_candles: int = 2
    ib_break_volume_mult: float = 1.5

    # =========================================================================
    # MARKET STATE
    # =========================================================================
    poc_no_trade_ticks: int = 2
    balance_ratio_threshold: float = 0.55
    displacement_multiplier: float = 1.5
    acceptance_volume_mult: float = 0.5
    acceptance_bar_count: int = 2

    # =========================================================================
    # DRIVE DETECTION
    # =========================================================================
    drive_proximity_ticks: int = 3
    drive_momentum_fade_threshold: float = 0.8

    # =========================================================================
    # AGGRESSION SCORING
    # =========================================================================
    aggression_footprint_weight: float = 1.0
    aggression_cvd_weight: float = 1.0
    aggression_big_trade_weight: float = 1.0
    aggression_absorption_weight: float = 0.5
    aggression_ofi_weight: float = 0.5
    aggression_confluence_weight: float = 0.5
    aggression_bubble_weight: float = 0.5
    min_aggression_score: float = 2.0
    pyramid_aggression_score: float = 3.0
    high_confidence_threshold: float = 3.0

    # =========================================================================
    # RISK MANAGEMENT
    # =========================================================================
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.020
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 0.030
    absolute_ceiling_pct: float = 0.010

    # =========================================================================
    # TRADE SETUP
    # =========================================================================
    min_rr_ratio: float = 1.5
    max_cushion_ticks: int = 10
    cushion_excellent_ticks: int = 3
    cushion_acceptable_ticks: int = 6

    # =========================================================================
    # PARTITION EXITS
    # =========================================================================
    p1_pct: float = 0.30
    p1_trigger_r: float = 0.33
    p2_pct: float = 0.50
    p3_pct: float = 0.20
    breakeven_trigger_r: float = 0.35
    trail_remaining_pct: float = 0.40
    counter_aggression_exit_count: int = 2

    # =========================================================================
    # PYRAMID
    # =========================================================================
    max_pyramid_adds: int = 2
    pyramid_add1_size: float = 1.0
    pyramid_add2_size: float = 0.5
    pyramid_proximity_ticks: int = 3

    # =========================================================================
    # TIME FILTERS
    # =========================================================================
    warm_up_minutes_mcx: int = 15
    warm_up_minutes_nse: int = 15
    dead_zone_start_hour: int = 12
    dead_zone_start_minute: int = 0
    dead_zone_end_hour: int = 13
    dead_zone_end_minute: int = 30
    preferred_window_1_start: str = "09:30"
    preferred_window_1_end: str = "11:30"
    preferred_window_2_start: str = "14:00"
    preferred_window_2_end: str = "15:30"

    # =========================================================================
    # DATA QUALITY
    # =========================================================================
    stale_threshold_seconds: int = 30
    tick_buffer_maxlen: int = 10000
    candle_buffer_maxlen: int = 200

    # =========================================================================
    # L2 DOM
    # =========================================================================
    l2_poll_interval_ms: int = 500
    liquidity_wall_multiplier: float = 5.0

    # =========================================================================
    # INSTRUMENT DEFAULTS
    # =========================================================================
    tick_size_naturalgas: float = 0.10
    tick_size_nifty: float = 0.05
    tick_size_banknifty: float = 0.05
    lot_size_naturalgas: int = 1250
    lot_size_nifty: int = 25
    lot_size_banknifty: int = 15
    point_value_naturalgas: int = 1250
    point_value_nifty: int = 25
    point_value_banknifty: int = 15

    # =========================================================================
    # SESSION TIMES (IST)
    # =========================================================================
    mcx_open_hour: int = 9
    mcx_open_minute: int = 0
    mcx_close_hour: int = 23
    mcx_close_minute: int = 30
    nse_open_hour: int = 9
    nse_open_minute: int = 15
    nse_close_hour: int = 15
    nse_close_minute: int = 30

    # =========================================================================
    # ATR
    # =========================================================================
    atr_period: int = 14
    avg_vol_period: int = 20
    avg_trade_size_period: int = 20


# Module-level singleton — frozen, no mutation after import
CFG = EngineConfig()