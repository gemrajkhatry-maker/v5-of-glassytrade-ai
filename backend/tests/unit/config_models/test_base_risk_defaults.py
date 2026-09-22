"""B2: base.yaml risk defaults must be safe even if an env overlay misses keys.

After load_config() with GLASSYTRADE_ENV=paper and strategy nse_options, the
effective risk block must stay within sane caps. Paper's allow_extreme_risk
must never be read as permission for catastrophic base defaults.

B7 note (document-only this task): .env DEFAULT_EXCHANGE=NSE can be shadowed
by strategy YAML segment/exchange codes (e.g. NFO); composition_root coord
config "exchange" still prefers the strategy path. Do not change exchange
semantics here — follow-up issue only.

Gate:
    PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit/config_models -q --no-header
"""

from app.config_models.loader import load_config


def test_base_risk_defaults_are_not_catastrophic(monkeypatch):
    """Paper + nse_options must inherit safe caps even if an overlay misses keys."""
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config()
    assert cfg.risk.risk_per_trade_pct <= 0.02, cfg.risk.risk_per_trade_pct
    assert cfg.risk.max_daily_loss_pct <= 0.05, cfg.risk.max_daily_loss_pct
    assert cfg.risk.portfolio_notional_cap <= 0.80
