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
