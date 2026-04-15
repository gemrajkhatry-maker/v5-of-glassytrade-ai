"""ConfigLoader — loads YAML config hierarchy and produces SystemConfig.

Merge sequence (strictly enforced):
  STEP 1: Load base.yaml → establishes ALL defaults
  STEP 2: Load environments/{GLASSYTRADE_ENV}.yaml → deep-merge overrides base
  STEP 3: Load strategies/*.yaml → deep-merge overrides result
  STEP 4: Read ENV vars for SECRETS ONLY → API keys, tokens
  STEP 5: Build typed SystemConfig → immutable, frozen
  STEP 6: Run ConfigValidator → fail fast if invalid
  STEP 7: Log startup summary → human-readable at boot
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from app.config_models import (
    CostProfile,
    ExchangeConfig,
    FeatureFlags,
    LLMConfig,
    MLThresholds,
    RiskConfig,
    SymbolConfig,
    SystemConfig,
)

logger = logging.getLogger(__name__)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base dict. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, return empty dict if not found."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _parse_ml_thresholds(data: dict) -> MLThresholds:
    """Parse ML thresholds from YAML data."""
    ic = data.get("imbalance_continuation", {})
    rv = data.get("return_to_value", {})
    pb = data.get("probing_breakout", {})
    return MLThresholds(
        imbalance_continuation_long=ic.get("long", 0.55),
        imbalance_continuation_short=ic.get("short", 0.58),
        return_to_value_long=rv.get("long", 0.51),
        return_to_value_short=rv.get("short", 0.51),
        probing_breakout_long=pb.get("long", 0.58),
        probing_breakout_short=pb.get("short", 0.58),
    )


def _parse_symbol(name: str, data: dict) -> SymbolConfig:
    """Parse SymbolConfig from YAML data."""
    cp = data.get("cost_profile", {})
    return SymbolConfig(
        name=name,
        enabled=data.get("enabled", True),
        exchange=data.get("exchange", "NSE"),
        segment=data.get("segment", "NFO"),
        instrument_type=data.get("instrument_type", "OPT"),
        lot_size=data.get("lot_size", 25),
        tick_size=data.get("tick_size", 0.05),
        vp_bucket_size=data.get("vp_bucket_size", 10.0),
        vp_num_buckets=data.get("vp_num_buckets", 200),
        value_area_pct=data.get("value_area_pct", 0.70),
        lvn_threshold=data.get("lvn_threshold", 0.15),
        hvn_threshold=data.get("hvn_threshold", 2.00),
        lvn_persistence_bars=data.get("lvn_persistence_bars", 3),
        lvn_removal_threshold=data.get("lvn_removal_threshold", 0.30),
        imbalance_threshold=data.get("imbalance_threshold", 50.0),
        displacement_multiplier=data.get("displacement_multiplier", 1.5),
        displacement_min_bars=data.get("displacement_min_bars", 3),
        balance_ratio_threshold=data.get("balance_ratio_threshold", 0.70),
        no_trade_ticks_from_poc=data.get("no_trade_ticks_from_poc", 2),
        aggression_sigma=data.get("aggression_sigma", 2.5),
        cvd_slope_warning=data.get("cvd_slope_warning", 30.0),
        cvd_slope_hard_block=data.get("cvd_slope_hard_block", 50.0),
        cvd_slope_extreme=data.get("cvd_slope_extreme", 100.0),
        cvd_strong_slope=data.get("cvd_strong_slope", 2.0),
        cvd_rolling_bars=data.get("cvd_rolling_bars", 20),
        min_oi=data.get("min_oi", 500000),
        strike_interval=data.get("strike_interval", 50),
        strikes_around_atm=data.get("strikes_around_atm", 2),
        slippage_bps=data.get("slippage_bps", 15),
        max_notional_pct=data.get("max_notional_pct", 0.20),
        min_rr_ratio=data.get("min_rr_ratio", 1.5),
        moneyness_pct=data.get("moneyness_pct", 0.0),
        min_aggression_score=data.get("min_aggression_score", 2.0),
        pyramid_aggression_score=data.get("pyramid_aggression_score", 3.0),
        aggression_persistence_bars=data.get("aggression_persistence_bars", 3),
        ml_thresholds=_parse_ml_thresholds(data.get("ml_thresholds", {})),
        cost_profile=CostProfile(
            slippage_bps=cp.get("slippage_bps", 15),
            stt_pct=cp.get("stt_pct", 0.000625),
            exchange_fee_pct=cp.get("exchange_fee_pct", 0.000495),
            brokerage_per_order=cp.get("brokerage_per_order", 20.0),
            gst_on_brokerage_pct=cp.get("gst_on_brokerage_pct", 0.18),
            sebi_charges_pct=cp.get("sebi_charges_pct", 0.000001),
        ),
    )


def _parse_exchange(name: str, data: dict) -> ExchangeConfig:
    """Parse ExchangeConfig from YAML data."""
    symbols = {}
    for sym_name, sym_data in data.get("symbols", {}).items():
        symbols[sym_name] = _parse_symbol(sym_name, sym_data)
    return ExchangeConfig(
        name=name,
        enabled=data.get("enabled", True),
        segment=data.get("segment", ""),
        session_open=data.get("session_open", "09:15"),
        session_close=data.get("session_close", "15:15"),
        warmup_minutes=data.get("warmup_minutes", 15),
        timezone=data.get("timezone", "Asia/Kolkata"),
        eia_suppression_minutes=data.get("eia_suppression_minutes", 15),
        symbols=symbols,
    )


def load_config(
    config_dir: str | None = None,
    strategy: str | None = None  # NEW: strategy name
) -> SystemConfig:
    """Load SystemConfig from YAML hierarchy.

    Args:
        config_dir: Path to config/ directory. Defaults to backend/config/
        strategy: Strategy name (e.g., "mcx_options", "nse_options").
                  If None, reads from GLASSYTRADE_STRATEGY env var.

    Returns:
        Frozen SystemConfig object
    
    Merge sequence (strictly enforced):
      STEP 1: Load base.yaml → establishes ALL defaults
      STEP 2: Load environments/{GLASSYTRADE_ENV}.yaml → deep-merge overrides base
      STEP 3: Load strategies/{strategy}.yaml → deep-merge overrides result
      STEP 4: Read ENV vars for SECRETS ONLY → API keys, tokens
      STEP 5: Build typed SystemConfig → immutable, frozen
      STEP 6: Run ConfigValidator → fail fast if invalid
      STEP 7: Log startup summary → human-readable at boot
    """
    if config_dir is None:
        config_dir = str(Path(__file__).resolve().parent.parent.parent / "config")
    config_path = Path(config_dir)

    # STEP 1: Load base.yaml
    base_data = _load_yaml(config_path / "base.yaml")

    # STEP 2: Load environment override
    env_name = os.environ.get("GLASSYTRADE_ENV", "paper")
    env_data = _load_yaml(config_path / "environments" / f"{env_name}.yaml")
    merged = _deep_merge(base_data, env_data)

    # STEP 3: Load strategy overrides (NEW)
    if strategy is None:
        strategy = os.environ.get("GLASSYTRADE_STRATEGY")
    
    if strategy:
        strat_path = config_path / "strategies" / f"{strategy}.yaml"
        strat_data = _load_yaml(strat_path)
        if strat_data:
            merged = _deep_merge(merged, strat_data)
            logger.info("Loaded strategy: %s", strategy)
        else:
            logger.warning("Strategy file not found: %s", strat_path)
    else:
        # Load any existing strategy files for backward compatibility
        strategies_dir = config_path / "strategies"
        if strategies_dir.exists():
            for f in sorted(strategies_dir.glob("*.yaml")):
                strat_data = _load_yaml(f)
                merged = _deep_merge(merged, strat_data)

    # STEP 4: Load feature flags
    flags_data = _load_yaml(config_path / "feature_flags.yaml")
    flags_raw = flags_data.get("features", flags_data)
    flags = FeatureFlags(
        true_delta_lee_ready=flags_raw.get("true_delta_lee_ready", False),
        realistic_cost_model=flags_raw.get("realistic_cost_model", False),
        parallel_symbol_sessions=flags_raw.get("parallel_symbol_sessions", False),
        duckdb_storage=flags_raw.get("duckdb_storage", False),
        short_signals_enabled=flags_raw.get("short_signals_enabled", False),
        risk_tier_engine=flags_raw.get("risk_tier_engine", False),
        initial_balance_engine=flags_raw.get("initial_balance_engine", False),
        correlation_guard=flags_raw.get("correlation_guard", True),
        iv_vix_features=flags_raw.get("iv_vix_features", False),
        walk_forward_validation=flags_raw.get("walk_forward_validation", False),
        shap_feature_pruning=flags_raw.get("shap_feature_pruning", False),
        llm_entry_gate=False,  # HARDCODED false
        llm_pre_candle_advisory=flags_raw.get("llm_pre_candle_advisory", True),
        llm_overseer=flags_raw.get("llm_overseer", True),
        llm_post_trade=flags_raw.get("llm_post_trade", True),
        scalp_engine_enabled=flags_raw.get("scalp_engine_enabled", False),
        ib_breakout_scalp=flags_raw.get("ib_breakout_scalp", False),
        print_level_trigger=flags_raw.get("print_level_trigger", False),
    )

    # STEP 5: Parse into typed objects
    sys_data = merged.get("system", {})
    risk_data = merged.get("risk", {})
    llm_data = merged.get("llm", {})

    exchanges = {}
    for ex_name, ex_data in merged.get("exchanges", {}).items():
        exchanges[ex_name] = _parse_exchange(ex_name, ex_data)

    config = SystemConfig(
        name=sys_data.get("name", "GlassyTrade AI"),
        version=sys_data.get("version", "2.0.0"),
        candle_timeframe_minutes=sys_data.get("candle_timeframe_minutes", 5),
        tick_history_depth=sys_data.get("tick_history_depth", 500),
        db_path=sys_data.get("db_path", "glassytrade.db"),
        log_level=env_data.get("log_level", sys_data.get("log_level", "INFO")),
        capital=float(sys_data.get("capital", 5000000)),
        environment=env_name,
        broker_mode=env_data.get("broker_mode", merged.get("broker_mode", "paper")),
        exchanges=exchanges,
        risk=RiskConfig(
            risk_per_trade_pct=risk_data.get("risk_per_trade_pct", 0.005),
            max_daily_loss_pct=risk_data.get("max_daily_loss_pct", 0.02),
            max_consecutive_losses=risk_data.get("max_consecutive_losses", 3),
            max_drawdown_pct=risk_data.get("max_drawdown_pct", 0.03),
            absolute_ceiling_pct=risk_data.get("absolute_ceiling_pct", 0.01),
            max_concurrent_positions=risk_data.get("max_concurrent_positions", 5),
            portfolio_notional_cap=risk_data.get("portfolio_notional_cap", 0.60),
            per_symbol_notional_cap=risk_data.get("per_symbol_notional_cap", 0.20),
            kelly_fraction=risk_data.get("kelly_fraction", 0.25),
            kelly_win_prob=risk_data.get("kelly_win_prob", 0.55),
            kelly_win_loss_ratio=risk_data.get("kelly_win_loss_ratio", 2.0),
            bootstrap_trade_count=risk_data.get("bootstrap_trade_count", 30),
        ),
        llm=LLMConfig(
            model_id=llm_data.get("model_id", "glassytrade-qwen-mlx-fused"),
            reasoning_model_id=llm_data.get("reasoning_model_id", ""),
            temperature_entry=llm_data.get("temperature_entry", 0.4),
            temperature_overseer=llm_data.get("temperature_overseer", 0.3),
            max_tokens=llm_data.get("max_tokens", 120),
            timeout_seconds=llm_data.get("timeout_seconds", 15),
            instruction=llm_data.get("instruction", ""),
        ),
        flags=flags,
    )

    # STEP 6: Validate
    from app.config_models.validator import validate_config

    validate_config(config)

    # STEP 7: Log summary
    _log_startup_summary(config)

    return config


def _log_startup_summary(config: SystemConfig) -> None:
    """Log human-readable config snapshot at boot."""
    logger.info("=" * 60)
    logger.info("  GlassyTrade AI — Startup Configuration")
    logger.info("=" * 60)
    logger.info(
        "  Environment: %s (broker_mode=%s)", config.environment, config.broker_mode
    )
    logger.info("  Capital: ₹%.0f", config.capital)
    logger.info("  Log level: %s", config.log_level)
    logger.info("  Active symbols: %s", config.active_symbols())
    logger.info("  Active exchanges: %s", [ex.name for ex in config.active_exchanges()])
    logger.info(
        "  Risk: per_trade=%.2f%% daily_loss=%.2f%% max_positions=%d",
        config.risk.risk_per_trade_pct * 100,
        config.risk.max_daily_loss_pct * 100,
        config.risk.max_concurrent_positions,
    )
    logger.info("  Feature flags:")
    for fname in (
        "true_delta_lee_ready",
        "realistic_cost_model",
        "parallel_symbol_sessions",
        "duckdb_storage",
        "short_signals_enabled",
        "risk_tier_engine",
        "initial_balance_engine",
        "correlation_guard",
        "iv_vix_features",
        "walk_forward_validation",
        "llm_entry_gate",
        "llm_pre_candle_advisory",
        "llm_overseer",
        "llm_post_trade",
        "scalp_engine_enabled",
    ):
        val = getattr(config.flags, fname, None)
        if val:
            logger.info("    %s: %s", fname, val)
    logger.info("=" * 60)
