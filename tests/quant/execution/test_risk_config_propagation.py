import logging

import pytest

from quant.execution.risk import SessionRisk


def test_live_config_uses_the_house_money_floor(monkeypatch):
    from app.config_models.loader import load_config

    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")

    config = load_config(strategy="nse_options")

    assert config.risk.risk_per_trade_pct == pytest.approx(0.0025)


def test_effective_risk_state_reports_the_floor():
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.002,
        day_of_week=1,
    )
    state = risk.state()

    assert state.base_risk_pct == pytest.approx(0.002)
    assert state.effective_base_risk_pct == pytest.approx(0.0025)
    assert state.risk_per_trade_pct == pytest.approx(0.0025)
    assert state.cushion_tier == "CONSERVATIVE"


def test_risk_state_exposes_configured_limits_and_effective_tier():
    risk = SessionRisk(
        starting_equity=1_000_000,
        base_risk_pct=0.0025,
        max_daily_loss_pct=0.017,
        max_consecutive_losses=5,
        day_of_week=1,
    )
    state = risk.state()

    assert state.max_daily_loss_pct == pytest.approx(0.017)
    assert state.max_consecutive_losses == 5
    assert state.effective_hmp_tier == "CONSERVATIVE"


def test_startup_summary_reports_effective_live_base(monkeypatch, caplog):
    from app.config_models.loader import load_config

    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")

    with caplog.at_level(logging.INFO, logger="app.config_models.loader"):
        load_config(strategy="nse_options")

    assert "effective_base=0.25%" in caplog.text
    assert "hmp_tier=CONSERVATIVE" in caplog.text
    assert "max_consecutive_losses=2" in caplog.text
