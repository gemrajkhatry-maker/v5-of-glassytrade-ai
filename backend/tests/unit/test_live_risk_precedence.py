"""Live environment risk limits must dominate strategy overrides."""

from __future__ import annotations

import yaml
import pytest

from app.config_models import ExchangeConfig, RiskConfig, SymbolConfig, SystemConfig
from app.config_models.loader import load_config
from app.config_models.validator import ConfigValidationError, validate_config


_REQUIRED_RISK = {
    "risk_per_trade_pct": 0.0025,
    "max_daily_loss_pct": 0.01,
    "max_consecutive_losses": 2,
    "max_trades_per_session": 6,
    "max_drawdown_pct": 0.03,
    "absolute_ceiling_pct": 0.01,
    "max_concurrent_positions": 3,
    "portfolio_notional_cap": 0.60,
    "per_symbol_notional_cap": 0.20,
}


def test_live_environment_risk_caps_override_strategy(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")

    config = load_config(strategy="nse_options")

    assert config.environment == "live"
    assert config.risk.risk_per_trade_pct == 0.0025
    assert config.risk.max_daily_loss_pct == 0.01
    assert config.risk.max_consecutive_losses == 2
    assert config.risk.portfolio_notional_cap <= 0.80


def _write_minimal_live_config(tmp_path, risk: dict):
    config_dir = tmp_path / "config"
    (config_dir / "environments").mkdir(parents=True)
    (config_dir / "strategies").mkdir()
    (config_dir / "base.yaml").write_text(
        yaml.safe_dump(
            {
                "system": {"capital": 1_000_000},
                "exchanges": {
                    "TEST": {
                        "enabled": True,
                        "session_open": "09:00",
                        "session_close": "17:00",
                        "symbols": {"TEST": {"enabled": True, "lot_size": 1}},
                    }
                },
            }
        )
    )
    (config_dir / "environments" / "live.yaml").write_text(
        yaml.safe_dump(
            {"environment": "live", "broker_mode": "live", "risk": risk}
        )
    )
    return config_dir


def test_live_boot_fails_when_required_risk_setting_is_missing(tmp_path, monkeypatch):
    risk = dict(_REQUIRED_RISK)
    del risk["max_daily_loss_pct"]
    config_dir = _write_minimal_live_config(tmp_path, risk)
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")

    with pytest.raises(ValueError, match="max_daily_loss_pct"):
        load_config(config_dir=str(config_dir), strategy="missing")


def test_live_boot_fails_for_non_positive_risk_value(tmp_path, monkeypatch):
    risk = dict(_REQUIRED_RISK, risk_per_trade_pct=0.0)
    config_dir = _write_minimal_live_config(tmp_path, risk)
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")

    with pytest.raises(ConfigValidationError, match="RULE-14"):
        load_config(config_dir=str(config_dir), strategy="missing")


def test_live_risk_invariants_reject_symbol_cap_above_portfolio_cap():
    config = SystemConfig(
        environment="live",
        broker_mode="live",
        capital=1_000_000,
        risk=RiskConfig(portfolio_notional_cap=0.20, per_symbol_notional_cap=0.30),
        exchanges={
            "TEST": ExchangeConfig(
                name="TEST",
                symbols={"TEST": SymbolConfig(name="TEST")},
            )
        },
    )

    with pytest.raises(ConfigValidationError, match="per_symbol_notional_cap"):
        validate_config(config)
