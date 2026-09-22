"""Portfolio risk YAML keys must land on RiskConfig (B1).

``backend/config/strategies/{nse,mcx}_options.yaml`` declare
``risk.max_portfolio_daily_loss_pct`` and ``risk.max_portfolio_risk_pct``,
which ``_coordinator_risk_config`` already forwards to the engines'
``PortfolioRiskAuthority`` — but only when ``RiskConfig`` actually carries
them. Without the typed fields the loader drops the keys on the floor and
the portfolio ceilings silently never apply.

Gate:
    PYTHONPATH=backend:. .venv/bin/python -m pytest \
        backend/tests/unit/config_models/test_portfolio_risk_fields.py \
        backend/tests/unit/application/test_composition_root.py -q --no-header
"""
from __future__ import annotations

from app.application.di.composition_root import _coordinator_risk_config
from app.config_models.loader import load_config


def test_strategy_yaml_portfolio_caps_reach_risk_config(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config()
    assert cfg.risk.max_portfolio_daily_loss_pct == 0.02
    assert cfg.risk.max_portfolio_risk_pct == 0.25


def test_strategy_yaml_portfolio_caps_are_sane_fractions(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config()
    assert 0 < cfg.risk.max_portfolio_daily_loss_pct <= 1
    assert 0 < cfg.risk.max_portfolio_risk_pct <= 1


def test_coordinator_risk_config_emits_portfolio_caps(monkeypatch):
    """Produces: composition passes the caps through to the coordinator."""
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config()
    out = _coordinator_risk_config(cfg)
    assert out["max_portfolio_daily_loss_pct"] == 0.02
    assert out["max_portfolio_risk_pct"] == 0.25
