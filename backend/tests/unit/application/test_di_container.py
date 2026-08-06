"""Basic tests for DI container wiring."""
import pytest


def test_composition_root_creates_container():
    """Verify composition_root.compose_container() returns a non-None container."""
    from config.consolidated import ConsolidatedConfig as Configuration
    from app.application.di.composition_root import compose_container

    config = Configuration.from_unified()
    container = compose_container(config)
    assert container is not None


def test_di_container_resolves_core_services():
    """Verify DIContainer can resolve market_data port."""
    from config.consolidated import ConsolidatedConfig as Configuration
    from app.application.di.composition_root import compose_container
    from quant.contracts.ports.market_data import IMarketData

    config = Configuration.from_unified()
    container = compose_container(config)
    market_data = container.resolve(IMarketData)
    assert market_data is not None
