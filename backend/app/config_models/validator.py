"""ConfigValidator — validates SystemConfig at startup.

All rules run at boot. Hard errors block boot. Warnings log but allow boot.

RULE-1 through RULE-12: hard errors (boot blocked)
WARN-1 through WARN-6: warnings (boot allowed, logged)
"""

from __future__ import annotations

import logging

from app.config_models import SystemConfig

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when a hard config validation rule fails."""


def validate_config(config: SystemConfig) -> None:
    """Run all validation rules. Raises ConfigValidationError on hard errors."""
    errors = []
    warnings = []

    # RULE-1: At least 1 active symbol exists
    active = config.active_symbols()
    if not active:
        errors.append("RULE-1: No active symbols. At least 1 must be enabled.")

    # RULE-2: In live mode: broker_mode must be "live"
    if config.is_live() and config.broker_mode != "live":
        errors.append("RULE-2: live environment requires broker_mode='live'.")

    # RULE-4: In live mode: capital ≥ ₹10,00,000
    if config.is_live() and config.capital < 1000000:
        errors.append(
            f"RULE-4: live mode requires capital >= ₹10,00,000. Got ₹{config.capital:,.0f}."
        )

    # RULE-5: risk_per_trade_pct ≤ 0.02
    if config.risk.risk_per_trade_pct > 0.02:
        errors.append(
            f"RULE-5: risk_per_trade_pct must be ≤ 2%. Got {config.risk.risk_per_trade_pct * 100:.2f}%."
        )

    # RULE-6: portfolio_notional_cap ≤ 0.80
    if config.risk.portfolio_notional_cap > 0.80:
        errors.append(
            f"RULE-6: portfolio_notional_cap must be ≤ 0.80. Got {config.risk.portfolio_notional_cap}."
        )

    # RULE-7: value_area_pct between 0.30 and 0.85 for all symbols
    for ex in config.exchanges.values():
        for sym in ex.symbols.values():
            if not (0.30 <= sym.value_area_pct <= 0.85):
                errors.append(
                    f"RULE-7: {sym.name} value_area_pct={sym.value_area_pct} outside [0.30, 0.85]."
                )

    # RULE-8: min_rr_ratio ≥ 1.0 for all symbols
    for ex in config.exchanges.values():
        for sym in ex.symbols.values():
            if sym.min_rr_ratio < 1.0:
                errors.append(
                    f"RULE-8: {sym.name} min_rr_ratio={sym.min_rr_ratio} < 1.0."
                )

    # RULE-9: sum of all symbol max_notional_pct ≤ 1.50
    total_notional = sum(
        sym.max_notional_pct
        for ex in config.exchanges.values()
        for sym in ex.symbols.values()
        if sym.enabled
    )
    if total_notional > 1.50:
        errors.append(f"RULE-9: sum of max_notional_pct={total_notional:.2f} > 1.50.")

    # RULE-10: cvd_slope_warning < cvd_slope_hard_block < cvd_slope_extreme
    for ex in config.exchanges.values():
        for sym in ex.symbols.values():
            if not (
                sym.cvd_slope_warning < sym.cvd_slope_hard_block < sym.cvd_slope_extreme
            ):
                errors.append(
                    f"RULE-10: {sym.name} CVD ordering invalid: "
                    f"{sym.cvd_slope_warning} < {sym.cvd_slope_hard_block} < {sym.cvd_slope_extreme}."
                )

    # RULE-11: lvn_threshold < lvn_removal_threshold
    for ex in config.exchanges.values():
        for sym in ex.symbols.values():
            if sym.lvn_threshold >= sym.lvn_removal_threshold:
                errors.append(
                    f"RULE-11: {sym.name} lvn_threshold={sym.lvn_threshold} >= lvn_removal_threshold={sym.lvn_removal_threshold}."
                )

    # RULE-12: ML model files exist for all active symbols
    import os

    model_dir = os.environ.get("ML_MODEL_DIR", "")
    if model_dir and os.path.isdir(model_dir):
        for sym_name in active:
            model_path = os.path.join(model_dir, f"{sym_name.lower()}_model.joblib")
            if not os.path.isfile(model_path):
                errors.append(
                    f"RULE-12: ML model file missing for {sym_name}: {model_path} not found."
                )

    # WARN-1: paper mode with unusually high capital
    if config.is_paper() and config.capital > 50000000:
        warnings.append(
            f"WARN-1: paper mode capital ₹{config.capital:,.0f} unusually high."
        )

    # WARN-2: short signals without walk-forward validation
    if config.flags.short_signals_enabled and not config.flags.walk_forward_validation:
        warnings.append(
            "WARN-2: short_signals_enabled but walk_forward_validation is false."
        )

    # WARN-3: risk_tier_engine enabled but bootstrap_trade_count < 30
    if config.flags.risk_tier_engine and config.risk.bootstrap_trade_count < 30:
        warnings.append(
            f"WARN-3: risk_tier_engine enabled but bootstrap_trade_count={config.risk.bootstrap_trade_count} < 30."
        )

    # WARN-4: min_rr_ratio below Fabio's recommended floor
    for ex in config.exchanges.values():
        for sym in ex.symbols.values():
            if sym.min_rr_ratio < 1.5:
                warnings.append(
                    f"WARN-4: {sym.name} min_rr_ratio={sym.min_rr_ratio} < 1.5 (below Fabio's floor)."
                )

    # WARN-6: MCX enabled with futures-only symbols
    for ex in config.exchanges.values():
        if ex.name == "MCX" and ex.enabled:
            futures_only = [
                name
                for name, sym in ex.symbols.items()
                if sym.instrument_type == "FUT" or sym.segment == "FUT"
            ]
            if futures_only:
                warnings.append(
                    f"WARN-6: MCX enabled — {', '.join(futures_only)} are futures-only (no option chain)."
                )

    # Log warnings
    for w in warnings:
        logger.warning(w)

    # Raise on hard errors
    if errors:
        for e in errors:
            logger.error(e)
        raise ConfigValidationError(
            f"Config validation failed with {len(errors)} errors:\n" + "\n".join(errors)
        )

    logger.info(
        "Config validation passed: %d symbols active, %d warnings.",
        len(active),
        len(warnings),
    )
