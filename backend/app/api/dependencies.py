"""Dependency injection — service graph factory.

Creates and wires the full service graph once at application startup.
FastAPI dependencies pull from the singleton graph.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.config import settings
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.application.services.trading_session import TradingSessionService
from app.domain.ports.market_data import MarketDataPort
from app.domain.ports.llm_inference import LLMInferencePort
from app.domain.ports.probability_inference import ProbabilityInferencePort
from app.domain.ports.storage import StoragePort
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService

logger = logging.getLogger(__name__)


class ServiceGraph:
    """Holds the singleton service instances."""

    def __init__(self) -> None:
        self.event_bus = InMemoryEventBus()
        self.market_data: MarketDataPort = DhanMarketDataAdapter(
            symbols=settings.DHAN_SYMBOLS,
            exchange=settings.DEFAULT_EXCHANGE,
            client_id=settings.DHAN_CLIENT_ID,
            access_token=settings.DHAN_ACCESS_TOKEN,
        )
        self.broker = PaperBrokerAdapter()
        self.llm_inference: LLMInferencePort = MLXInferenceAdapter()
        self.gen_ai_service = GenerativeAIService(llm_adapter=self.llm_inference)
        self.storage = SQLiteStorageAdapter()

        # Probability engine (LightGBM first-passage models)
        _model_dir = os.path.join(os.path.dirname(__file__), "..", "..", "models")
        _model_dir = os.path.normpath(_model_dir)
        self.probability_engine: ProbabilityInferencePort = LGBMProbabilityAdapter(
            model_dir=_model_dir,
        )
        logger.info("Probability engine ready=%s (model_dir=%s)",
                     self.probability_engine.is_ready(), _model_dir)

        self.trading_session = TradingSessionService(
            event_bus=self.event_bus,
            broker=self.broker,
            gen_ai_service=self.gen_ai_service,
            storage=self.storage,
            probability_engine=self.probability_engine,
        )

        # Pre-warm broker: load instrument cache (date-stamped, refreshed once/day).
        # ensure_initialized_sync() is thread-safe and idempotent — no race with
        # the async gameloop path that calls _ensure_initialized() later.
        import concurrent.futures as _cf

        # Pre-warm broker: block until instrument cache is ready (required for scanner)
        _init_pool = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            _fut = _init_pool.submit(self.market_data.ensure_initialized_sync, 300)
            _fut.result(timeout=300)
            logger.info("Broker pre-warm complete (instrument cache ready)")
        except (_cf.TimeoutError, Exception):
            logger.warning("Broker pre-warm failed/timed out (non-critical — market may be closed)")
        finally:
            _init_pool.shutdown(wait=False)

        # Auto-select option contracts on startup (multi-symbol)
        self.engine = None  # Set by lifespan after TradingEngine.start()
        self.active_symbols: list[str] = [settings.DEFAULT_SYMBOL]
        _scan_pool = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            from app.domain.fabio_ai.services.option_scanner import OptionScannerService

            def _scan():
                _scanner = OptionScannerService(self.market_data)
                return _scanner.scan_top_n(
                    n=settings.SCANNER_TOP_N,
                    underlyings=settings.SCANNER_UNDERLYINGS,
                    preferred_option_type=settings.SCANNER_OPTION_TYPE or None,
                    exchange=settings.DEFAULT_EXCHANGE,
                    expiry_index=settings.SCANNER_EXPIRY_INDEX,
                    top_per_underlying=settings.SCANNER_TOP_N,
                )

            _results = _scan_pool.submit(_scan).result(timeout=120)

            if _results:
                # Scanner already validates LTP from chain — no redundant API calls
                _final = [r for r in _results if r.ltp > 0]
                if not _final:
                    _final = _results
                self.active_symbols = [r.symbol for r in _final]
                for i, r in enumerate(_final, 1):
                    logger.info("Auto-selected #%d: %s (LTP=%.2f, OI=%d, Score=%.1f, Bias=%s)",
                               i, r.symbol, r.ltp, r.oi, r.score, r.bias)
            else:
                logger.warning("Option scan returned no results — using DEFAULT_SYMBOL=%s", settings.DEFAULT_SYMBOL)
        except (_cf.TimeoutError, Exception):
            logger.warning("Option scanner failed/timed out — using DEFAULT_SYMBOL=%s", settings.DEFAULT_SYMBOL)
        finally:
            _scan_pool.shutdown(wait=False)


@lru_cache(maxsize=1)
def get_service_graph() -> ServiceGraph:
    """Singleton service graph created once."""
    return ServiceGraph()


# FastAPI dependency helpers

def get_market_data() -> MarketDataPort:
    return get_service_graph().market_data


def get_trading_session() -> TradingSessionService:
    return get_service_graph().trading_session


def get_gen_ai_service() -> GenerativeAIService:
    return get_service_graph().gen_ai_service


def get_storage() -> StoragePort:
    return get_service_graph().storage


def get_active_symbol() -> str:
    """Backward compat: return first (highest-scored) symbol."""
    return get_service_graph().active_symbols[0]


def get_active_symbols() -> list[str]:
    return get_service_graph().active_symbols
