"""API dependency injection — thin wrappers over ServiceGraph.

Only imported by main.py and routers at startup. Keep imports minimal to avoid
cascading import chains through domain services.
"""

from fastapi import Request

from app.application.service_graph import ServiceGraph
from config.config import Configuration

# Lazy imports: each getter imports only what it needs, only when called.
# This prevents import cascade failures when domain services have missing deps.

# Module-level singleton (matches original behaviour)
_service_graph: ServiceGraph | None = None


def set_service_graph(service_graph: ServiceGraph) -> None:
    """Register the application ServiceGraph as the process-wide singleton."""
    global _service_graph
    _service_graph = service_graph


def get_service_graph() -> ServiceGraph:
    """Return the process-wide ServiceGraph set at app startup.

    Callers must not rely on implicit construction: a second graph would duplicate
    heavy adapters (MLX, DB, LGBM) and diverge from ``app.state.service_graph``.
    """
    global _service_graph
    if _service_graph is None:
        raise RuntimeError(
            "ServiceGraph not initialized: run set_service_graph() from app startup "
            "before using dependency getters."
        )
    return _service_graph


async def get_service_graph_from_request(request: Request) -> ServiceGraph:
    """Get service graph from FastAPI app state (preferred for routers)."""
    return request.app.state.service_graph


def get_market_data():
    """Dependency: Market data adapter."""
    from app.domain.ports.market_data import IMarketData
    return get_service_graph().get(IMarketData)


def get_storage():
    """Dependency: Storage adapter."""
    from app.domain.ports.storage import IStorage
    return get_service_graph().get(IStorage)


def get_gen_ai_service():
    """Dependency: Generative AI service."""
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    return get_service_graph().get(GenerativeAIService)


def get_scanner_service():
    """Dependency: Scanner service."""
    from app.domain.services.scanner_service import ScannerService
    return get_service_graph().get(ScannerService)


def get_amt_analysis_service():
    """Dependency: AMT analysis service."""
    from app.domain.services.amt_analysis_service import AMTAnalysisService
    return get_service_graph().get(AMTAnalysisService)


def get_gate_pipeline():
    """Dependency: Gate pipeline."""
    from app.domain.services.gate_pipeline import GatePipeline
    return get_service_graph().get(GatePipeline)


def get_volume_profile_service():
    """Dependency: Volume profile service."""
    from app.domain.services.volume_profile_service import VolumeProfileService
    return get_service_graph().get(VolumeProfileService)


def get_lvn_analyzer():
    """Dependency: LVN analyzer."""
    from app.domain.services.lvn_analyzer import LVNAnalyzer
    return get_service_graph().get(LVNAnalyzer)


def get_market_state_classifier():
    """Dependency: Market state classifier."""
    from app.domain.services.market_state_classifier import MarketStateClassifier
    return get_service_graph().get(MarketStateClassifier)


def get_aggression_scorer():
    """Dependency: Aggression scorer."""
    from app.domain.services.aggression_scorer import AggressionScorer
    return get_service_graph().get(AggressionScorer)


def get_signal_generator():
    """Dependency: Signal generator."""
    from app.domain.services.signal_generator import SignalGenerator
    return get_service_graph().get(SignalGenerator)


def get_configuration():
    """Dependency: Application configuration."""
    return get_service_graph().get(Configuration)


def get_trading_session(request: Request):
    """Dependency: live trading session from the running app graph."""
    return request.app.state.service_graph.trading_session


def get_active_symbols(request: Request):
    """Dependency: active symbols selected by scanner / config."""
    return list(request.app.state.service_graph.active_symbols)
