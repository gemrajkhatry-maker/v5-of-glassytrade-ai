"""API dependency injection — thin wrappers over ServiceGraph.

Only imported by main.py and routers at startup. Keep imports minimal to avoid
cascading import chains through domain services.

All service access goes through FastAPI app.state.service_graph — there is no
module-level singleton.
"""

from fastapi import Request

from app.application.service_graph import ServiceGraph


def get_service_graph_from_request(request: Request) -> ServiceGraph:
    """Get service graph from FastAPI app state."""
    return request.app.state.service_graph


def get_market_data(request: Request):
    """Dependency: Market data adapter."""
    from app.domain.ports.market_data import IMarketData
    return request.app.state.service_graph.get(IMarketData)


def get_storage(request: Request):
    """Dependency: Storage adapter."""
    from app.domain.ports.storage import IStorage
    return request.app.state.service_graph.get(IStorage)


def get_gen_ai_service(request: Request):
    """Dependency: Generative AI service."""
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    return request.app.state.service_graph.get(GenerativeAIService)


def get_configuration(request: Request):
    """Dependency: Application configuration."""
    return request.app.state.service_graph.get(Configuration)


def get_trading_session(request: Request):
    """Dependency: live trading session from the running app graph."""
    return request.app.state.service_graph.trading_session


def get_active_symbols(request: Request):
    """Dependency: active symbols selected by scanner / config."""
    return list(request.app.state.service_graph.active_symbols)
