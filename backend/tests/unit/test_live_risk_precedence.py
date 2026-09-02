"""Live environment risk limits must dominate strategy overrides."""

import os

from app.config_models.loader import load_config


def test_live_environment_risk_caps_override_strategy(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")

    config = load_config(strategy="nse_options")

    assert config.environment == "live"
    assert config.risk.risk_per_trade_pct == 0.002
    assert config.risk.max_daily_loss_pct == 0.01
    assert config.risk.max_consecutive_losses == 2
    assert config.risk.portfolio_notional_cap <= 0.80
