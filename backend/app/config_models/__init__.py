"""Typed SystemConfig — frozen, immutable, single source of truth for all config.

This is the ONLY config object passed through ServiceGraph. No other config
source exists at runtime. All values come from the YAML merge sequence:
  base.yaml → environments/{env}.yaml → strategies/*.yaml → ENV vars (secrets only)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass(frozen=True)
class CostProfile:
    """Per-symbol cost model for realistic PnL simulation."""

    slippage_bps: float = 15.0
    stt_pct: float = 0.000625
    exchange_fee_pct: float = 0.000495
    brokerage_per_order: float = 20.0
    gst_on_brokerage_pct: float = 0.18
    sebi_charges_pct: float = 0.000001


@dataclass(frozen=True)
class MLThresholds:
    """Per-playbook ML probability thresholds."""

    imbalance_continuation_long: float = 0.55
    imbalance_continuation_short: float = 0.58
    return_to_value_long: float = 0.51
    return_to_value_short: float = 0.51
    probing_breakout_long: float = 0.58
    probing_breakout_short: float = 0.58


@dataclass(frozen=True)
class SymbolConfig:
    """Complete per-symbol configuration. Every field from base.yaml."""

    name: str = ""
    enabled: bool = True
    exchange: str = "NSE"
    segment: str = "NFO"
    instrument_type: str = "OPT"
    # The loader (config_models/loader.py) REQUIRES lot_size from YAML and
    # always overrides this default; it only serves direct (test) construction.
    # Kept at the exchange-authoritative NIFTY value (65, Aug 2026) so a
    # constructed config is never silently wrong (was 25, off by ~2.6x).
    lot_size: int = 65
    tick_size: float = 0.05
    vp_bucket_size: float = 10.0
    vp_num_buckets: int = 200
    value_area_pct: float = 0.70
    lvn_threshold: float = 0.15
    hvn_threshold: float = 2.00
    lvn_persistence_bars: int = 3
    lvn_removal_threshold: float = 0.30
    imbalance_threshold: float = 50.0
    displacement_multiplier: float = 1.5
    displacement_min_bars: int = 3
    balance_ratio_threshold: float = 0.70
    no_trade_ticks_from_poc: int = 2
    aggression_sigma: float = 2.5
    cvd_slope_warning: float = 30.0
    cvd_slope_hard_block: float = 50.0
    cvd_slope_extreme: float = 100.0
    cvd_strong_slope: float = 2.0
    cvd_rolling_bars: int = 20
    min_oi: int = 500000
    strike_interval: int = 50
    strikes_around_atm: int = 2
    slippage_bps: float = 15.0
    max_notional_pct: float = 0.20
    min_rr_ratio: float = 1.5
    moneyness_pct: float = 0.0  # |strike - spot| / spot for ATM/OTM classification
    min_aggression_score: float = 2.0
    pyramid_aggression_score: float = 3.0
    aggression_persistence_bars: int = 3
    ml_thresholds: MLThresholds = field(default_factory=MLThresholds)
    cost_profile: CostProfile = field(default_factory=CostProfile)


@dataclass(frozen=True)
class ExchangeConfig:
    """Per-exchange configuration."""

    name: str = ""
    enabled: bool = True
    segment: str = ""
    session_open: str = "09:15"
    session_close: str = "15:15"
    warmup_minutes: int = 15
    timezone: str = "Asia/Kolkata"
    eia_suppression_minutes: int = 15
    symbols: dict[str, SymbolConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskConfig:
    """Global risk configuration."""

    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 0.03
    absolute_ceiling_pct: float = 0.01
    max_concurrent_positions: int = 5
    portfolio_notional_cap: float = 0.60
    per_symbol_notional_cap: float = 0.20
    kelly_fraction: float = 0.25
    kelly_win_prob: float = 0.55
    kelly_win_loss_ratio: float = 2.0
    bootstrap_trade_count: int = 30


@dataclass(frozen=True)
class FeatureFlags:
    """All feature flags with defaults. Matches spec Phase -1, Component 3."""

    # Phase 0 flags
    true_delta_lee_ready: bool = False
    realistic_cost_model: bool = False

    # Phase 1 flags
    parallel_symbol_sessions: bool = False

    # Phase 2 flags
    short_signals_enabled: bool = False
    risk_tier_engine: bool = False

    # Phase 3 flags
    walk_forward_validation: bool = False

    # Phase 4 flags
    scalp_engine_enabled: bool = False
    ib_breakout_scalp: bool = False
    print_level_trigger: bool = False


@dataclass(frozen=True)
class GapFillConfig:
    """Configuration for gap detection and filling in streaming data."""
    
    enabled: bool = True
    interval_seconds: int = 300  # Check every 5 minutes
    min_gap_seconds: int = 60  # Only fill gaps > 60 seconds
    max_lookback_seconds: int = 600  # Look back 10 minutes
    max_fill_age_seconds: int = 120  # Don't fill gaps newer than 2 minutes


@dataclass(frozen=True)
class SystemConfig:
    """Top-level system configuration — frozen, immutable, single source of truth.

    Passed through ServiceGraph. No other config source at runtime.
    """

    name: str = "GlassyTrade AI"
    version: str = "2.0.0"
    candle_timeframe_minutes: int = 1
    tick_history_depth: int = 500
    db_path: str = "glassytrade.db"
    log_level: str = "INFO"
    capital: float = 5000000.0
    environment: str = "development"
    broker_mode: str = "paper"
    exchanges: dict[str, ExchangeConfig] = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    gap_fill: GapFillConfig = field(default_factory=GapFillConfig)

    def symbol_config(self, symbol_name: str) -> SymbolConfig | None:
        """Find SymbolConfig by name across all exchanges."""
        for ex in self.exchanges.values():
            if symbol_name in ex.symbols:
                return ex.symbols[symbol_name]
        return None

    def active_symbols(self) -> list[str]:
        """Return list of all enabled symbol names."""
        result = []
        for ex in self.exchanges.values():
            if ex.enabled:
                for name, sym in ex.symbols.items():
                    if sym.enabled:
                        result.append(name)
        return result

    def active_exchanges(self) -> list[ExchangeConfig]:
        """Return list of enabled exchanges."""
        return [ex for ex in self.exchanges.values() if ex.enabled]

    def is_live(self) -> bool:
        return self.environment == "live"

    def is_paper(self) -> bool:
        return self.environment == "paper"
