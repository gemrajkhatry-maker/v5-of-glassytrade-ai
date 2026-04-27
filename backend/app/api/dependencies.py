"""API dependency injection — thin wrappers over ServiceGraph.

Only imported by main.py and routers at startup. Keep imports minimal to avoid
cascading import chains through domain services.

All service access goes through FastAPI app.state.service_graph — there is no
module-level singleton.
"""

from fastapi import Request

from app.application.service_graph import ServiceGraph
from config.config import Configuration


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


def get_volume_profile_service(request: Request):
    """Dependency: Volume profile service."""
    from app.domain.services.volume_profile_service import VolumeProfileService
    return request.app.state.service_graph.get(VolumeProfileService)


def get_lvn_analyzer(request: Request):
    """Dependency: LVN analyzer."""
    from app.domain.services.lvn_analyzer import LVNAnalyzer
    return request.app.state.service_graph.get(LVNAnalyzer)


def get_market_state_classifier(request: Request):
    """Dependency: Market state classifier."""
    from app.domain.services.market_state_classifier import MarketStateClassifier
    return request.app.state.service_graph.get(MarketStateClassifier)


def get_aggression_scorer(request: Request):
    """Dependency: Aggression scorer."""
    from app.domain.services.aggression_scorer import AggressionScorer
    return request.app.state.service_graph.get(AggressionScorer)


def get_signal_generator(request: Request):
    """Dependency: Signal generator."""
    from app.domain.services.signal_generator import SignalGenerator
    return request.app.state.service_graph.get(SignalGenerator)


def get_configuration(request: Request):
    """Dependency: Application configuration."""
    return request.app.state.service_graph.get(Configuration)


def get_trading_session(request: Request):
    """Dependency: live trading session from the running app graph."""
    return request.app.state.service_graph.trading_session


def get_active_symbols(request: Request):
    """Dependency: active symbols selected by scanner / config."""
    return list(request.app.state.service_graph.active_symbols)
