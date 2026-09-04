"""Basic tests for DI container wiring."""
import pytest


def _config():
    from app.config import settings
    mode = settings.get_mode_config()
    return mode.system_config if mode is not None else None


def test_composition_root_creates_container():
    """Verify composition_root.compose_container() returns a non-None container."""
    from app.application.di.composition_root import compose_container

    config = _config()
    container = compose_container(config)
    assert container is not None


def test_di_container_resolves_core_services():
    """Verify DIContainer can resolve market_data port."""
    from app.application.di.composition_root import compose_container
    from quant.contracts.ports.market_data import IMarketData

    config = _config()
    container = compose_container(config)
    market_data = container.resolve(IMarketData)
    assert market_data is not None


# ---------------------------------------------------------------------------
# Coordinator risk propagation — no silent defaults in the composition root
# ---------------------------------------------------------------------------


def test_coordinator_risk_config_matches_validated_config():
    """The coordinator receives the EXACT validated risk values, not literals."""
    from app.application.di.composition_root import _coordinator_risk_config

    config = _config()
    assert config is not None and config.risk is not None
    risk = _coordinator_risk_config(config)
    assert risk["risk_per_trade_pct"] == config.risk.risk_per_trade_pct
    assert risk["max_daily_loss_pct"] == config.risk.max_daily_loss_pct
    assert risk["max_consecutive_losses"] == config.risk.max_consecutive_losses
    assert risk["max_trades_per_session"] == config.risk.max_trades_per_session


def test_coordinator_risk_config_missing_value_fails_boot():
    """A missing/None risk field must abort startup, never fall back silently."""
    from dataclasses import replace

    from app.application.di.composition_root import _coordinator_risk_config
    from app.config_models import RiskConfig

    config = _config()
    assert config is not None
    # Simulate a future config model where a risk field is optional/absent
    # (the loader/validator would normally reject this earlier; the
    # composition root is the last line — it must raise, not default).
    broken = replace(config, risk=RiskConfig(max_consecutive_losses=None))
    with pytest.raises(ValueError, match="max_consecutive_losses"):
        _coordinator_risk_config(broken)


def test_coordinator_risk_config_no_risk_object_fails_boot():
    """Even a config without a risk block must fail loudly."""
    from types import SimpleNamespace

    from app.application.di.composition_root import _coordinator_risk_config

    bare = SimpleNamespace(candle_timeframe_minutes=5)
    # First required field evaluated (dict order) aborts with a named error.
    with pytest.raises(ValueError, match="config.risk.max_trades_per_session"):
        _coordinator_risk_config(bare)  # type: ignore[arg-type]
