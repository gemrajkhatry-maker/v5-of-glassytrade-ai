"""ConfigValidator — validates SystemConfig at startup.

All rules run at boot. Hard errors block boot. Warnings log but allow boot.

RULE-1 through RULE-13: hard errors (boot blocked)
WARN-1 through WARN-6: warnings (boot allowed, logged)

Refactored: each section is a standalone function (Cognitive ≤15 each)
so the main orchestrator stays readable.
"""

from __future__ import annotations

import logging
import math
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_models import SystemConfig

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when a hard config validation rule fails."""


# ---------------------------------------------------------------------------
# Section validators — each returns (errors, warnings)
# ---------------------------------------------------------------------------

def _validate_global(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """RULE-1, RULE-2, RULE-4, RULE-5, RULE-6, WARN-1."""
    errors, warnings = [], []

    active = config.active_symbols()
    if not active:
        errors.append("RULE-1: No active symbols. At least 1 must be enabled.")

    if config.is_live() and config.broker_mode != "live":
        errors.append("RULE-2: live environment requires broker_mode='live'.")

    if config.is_live() and config.capital < 1000000:
        errors.append(
            f"RULE-4: live mode requires capital >= ₹10,00,000. Got ₹{config.capital:,.0f}."
        )

    if config.is_live() and config.risk.risk_per_trade_pct > 0.02:
        errors.append(
            f"RULE-5: live mode risk_per_trade_pct must be ≤ 2%. Got {config.risk.risk_per_trade_pct * 100:.2f}%."
        )

    if config.is_live() and config.risk.portfolio_notional_cap > 0.80:
        errors.append(
            f"RULE-6: live mode portfolio_notional_cap must be ≤ 0.80. Got {config.risk.portfolio_notional_cap}."
        )

    if config.is_paper() and config.capital > 50000000:
        warnings.append(
            f"WARN-1: paper mode capital ₹{config.capital:,.0f} unusually high."
        )

    return errors, warnings


def _validate_symbol(name: str, sym: object) -> list[str]:
    """RULE-7, RULE-8, RULE-10, RULE-11, WARN-4 for one symbol."""
    errors = []

    if not (0.30 <= sym.value_area_pct <= 0.85):
        errors.append(
            f"RULE-7: {name} value_area_pct={sym.value_area_pct} outside [0.30, 0.85]."
        )

    if sym.min_rr_ratio < 1.0:
        errors.append(
            f"RULE-8: {name} min_rr_ratio={sym.min_rr_ratio} < 1.0."
        )

    if not (sym.cvd_slope_warning < sym.cvd_slope_hard_block < sym.cvd_slope_extreme):
        errors.append(
            f"RULE-10: {name} CVD ordering invalid: "
            f"{sym.cvd_slope_warning} < {sym.cvd_slope_hard_block} < {sym.cvd_slope_extreme}."
        )

    if sym.lvn_threshold >= sym.lvn_removal_threshold:
        errors.append(
            f"RULE-11: {name} lvn_threshold={sym.lvn_threshold} >= lvn_removal_threshold={sym.lvn_removal_threshold}."
        )

    return errors


def _validate_risk(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """RULE-14: risk values are finite, positive, and bounded for the mode."""
    errors = []
    risk = config.risk
    numeric_limits = {
        "risk_per_trade_pct": risk.risk_per_trade_pct,
        "max_daily_loss_pct": risk.max_daily_loss_pct,
        "max_drawdown_pct": risk.max_drawdown_pct,
        "absolute_ceiling_pct": risk.absolute_ceiling_pct,
        "portfolio_notional_cap": risk.portfolio_notional_cap,
        "per_symbol_notional_cap": risk.per_symbol_notional_cap,
    }
    for name, value in numeric_limits.items():
        if not math.isfinite(float(value)) or float(value) <= 0:
            errors.append(f"RULE-14: {name} must be finite and > 0. Got {value!r}.")

    integer_limits = {
        "max_consecutive_losses": risk.max_consecutive_losses,
        "max_trades_per_session": risk.max_trades_per_session,
        "max_concurrent_positions": risk.max_concurrent_positions,
    }
    for name, value in integer_limits.items():
        if isinstance(value, bool) or int(value) != value or int(value) < 1:
            errors.append(f"RULE-14: {name} must be a positive integer. Got {value!r}.")

    deployment = float(config.paper.capital_deployment_pct)
    if not math.isfinite(deployment) or not 0.0 < deployment <= 1.0:
        errors.append(
            "RULE-15: paper capital_deployment_pct must be finite and in (0, 1]. "
            f"Got {config.paper.capital_deployment_pct!r}."
        )

    if config.is_live() and config.paper.allow_extreme_risk:
        errors.append("RULE-15: live mode cannot enable paper allow_extreme_risk.")

    if (
        config.is_paper()
        and risk.risk_per_trade_pct >= 0.05
        and not config.paper.allow_extreme_risk
    ):
        errors.append(
            "RULE-15: paper risk_per_trade_pct >= 0.05 requires "
            "paper.allow_extreme_risk=true; use capital_deployment_pct for "
            "95% paper sizing."
        )

    if config.is_live():
        if risk.risk_per_trade_pct > 0.02:
            errors.append(
                f"RULE-14: live risk_per_trade_pct must be ≤ 0.02. Got {risk.risk_per_trade_pct}."
            )
        if risk.max_daily_loss_pct > risk.max_drawdown_pct:
            errors.append(
                "RULE-14: live max_daily_loss_pct must be ≤ max_drawdown_pct."
            )
        if risk.portfolio_notional_cap > 0.80:
            errors.append(
                f"RULE-14: live portfolio_notional_cap must be ≤ 0.80. Got {risk.portfolio_notional_cap}."
            )
        if risk.per_symbol_notional_cap > risk.portfolio_notional_cap:
            errors.append(
                "RULE-14: live per_symbol_notional_cap must be ≤ portfolio_notional_cap."
            )

    return errors, []


def _validate_symbols(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """RULE-7, RULE-8, RULE-9, RULE-10, RULE-11, WARN-4 across all symbols."""
    errors, warnings = [], []

    for ex in config.exchanges.values():
        for sym_name, sym in ex.symbols.items():
            errors.extend(_validate_symbol(sym_name, sym))

            if sym.min_rr_ratio < 1.5:
                warnings.append(
                    f"WARN-4: {sym_name} min_rr_ratio={sym.min_rr_ratio} < 1.5 (below Fabio's floor)."
                )

    total_notional = sum(
        sym.max_notional_pct
        for ex in config.exchanges.values()
        for sym in ex.symbols.values()
        if sym.enabled
    )
    if total_notional > 1.50:
        errors.append(f"RULE-9: sum of max_notional_pct={total_notional:.2f} > 1.50.")

    return errors, warnings


def _validate_features(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """WARN-2, WARN-3."""
    warnings = []

    if config.flags.short_signals_enabled and not config.flags.walk_forward_validation:
        warnings.append(
            "WARN-2: short_signals_enabled but walk_forward_validation is false."
        )

    if config.flags.risk_tier_engine and config.risk.bootstrap_trade_count < 30:
        warnings.append(
            f"WARN-3: risk_tier_engine enabled but bootstrap_trade_count={config.risk.bootstrap_trade_count} < 30."
        )

    return [], warnings


def _validate_mcx(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """WARN-6: MCX futures-only symbols."""
    warnings = []

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

    return [], warnings


def _validate_registry(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """RULE-13: YAML lot/tick/strike/session clock must match InstrumentRegistry."""
    from quant.contracts.instrument_registry import DEFAULT_REGISTRY
    from quant.contracts.timezones import (
        MCX_SESSION_CLOSE, MCX_SESSION_OPEN,
        NSE_SESSION_CLOSE, NSE_SESSION_OPEN,
    )

    errors = []
    session_windows = {
        "NSE": (NSE_SESSION_OPEN, NSE_SESSION_CLOSE),
        "MCX": (MCX_SESSION_OPEN, MCX_SESSION_CLOSE),
    }

    for ex in config.exchanges.values():
        windows = session_windows.get(ex.name)
        if windows:
            expected_open, expected_close = windows
            if ex.session_open and ex.session_open != expected_open.strftime("%H:%M"):
                errors.append(
                    f"RULE-13: {ex.name} session_open YAML={ex.session_open} registry={expected_open.strftime('%H:%M')}."
                )
            if ex.session_close and ex.session_close != expected_close.strftime("%H:%M"):
                errors.append(
                    f"RULE-13: {ex.name} session_close YAML={ex.session_close} registry={expected_close.strftime('%H:%M')}."
                )

        for sym_name, sym in ex.symbols.items():
            spec = DEFAULT_REGISTRY.try_resolve(sym_name)
            if spec is None:
                continue
            if int(sym.lot_size) != spec.lot_size:
                errors.append(
                    f"RULE-13: {sym_name} lot_size YAML={sym.lot_size} registry={spec.lot_size}."
                )
            if float(sym.tick_size) != spec.tick_size:
                errors.append(
                    f"RULE-13: {sym_name} tick_size YAML={sym.tick_size} registry={spec.tick_size}."
                )
            if int(sym.strike_interval) != int(spec.strike_interval):
                errors.append(
                    f"RULE-13: {sym_name} strike_interval YAML={sym.strike_interval} "
                    f"registry={int(spec.strike_interval)}."
                )

    return errors, []


def _validate_ml_models(config: "SystemConfig") -> tuple[list[str], list[str]]:
    """RULE-12: ML model files exist for all active symbols."""
    errors = []
    model_dir = os.environ.get("ML_MODEL_DIR", "")
    if model_dir and os.path.isdir(model_dir):
        for sym_name in config.active_symbols():
            model_path = os.path.join(model_dir, f"{sym_name.lower()}_model.joblib")
            if not os.path.isfile(model_path):
                errors.append(
                    f"RULE-12: ML model file missing for {sym_name}: {model_path} not found."
                )
    return errors, []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def validate_config(config: "SystemConfig") -> None:
    """Run all validation rules. Raises ConfigValidationError on hard errors."""
    all_errors: list[str] = []
    all_warnings: list[str] = []

    for validator in (
        _validate_global,
        _validate_risk,
        _validate_symbols,
        _validate_features,
        _validate_mcx,
        _validate_registry,
        _validate_ml_models,
    ):
        errors, warnings = validator(config)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    for w in all_warnings:
        logger.warning(w)

    if all_errors:
        for e in all_errors:
            logger.error(e)
        raise ConfigValidationError(
            f"Config validation failed with {len(all_errors)} errors:\n"
            + "\n".join(all_errors)
        )

    logger.info(
        "Config validation passed: %d symbols active, %d warnings.",
        len(config.active_symbols()),
        len(all_warnings),
    )
