"""Basic tests for DI container wiring."""
import pytest


def test_composition_root_creates_container():
    """Verify composition_root.compose_container() returns a non-None container."""
    from config.consolidated import ConsolidatedConfig as Configuration
    from app.application.di.composition_root import compose_container

    config = Configuration.from_unified()
    container = compose_container(config)
    assert container is not None


def test_service_graph_resolves_core_services():
    """Verify ServiceGraph can resolve trading_session and market_data."""
    from config.consolidated import ConsolidatedConfig as Configuration
    from app.application.service_graph import ServiceGraph
    from app.domain.ports.market_data import IMarketData

    config = Configuration.from_unified()
    graph = ServiceGraph(config)
    assert graph.trading_session is not None
    assert graph.get(IMarketData) is not None
