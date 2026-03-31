"""Dependency injection — service graph factory.

Creates and wires the full service graph once at application startup.
FastAPI dependencies pull from the singleton graph.

Architecture:
  - ExchangeConfig: Immutable value object with all NSE/MCX-specific settings
  - SymbolRegistry: Single source of truth for exchange↔symbol mapping
  - ExchangeStrategy: Port encapsulating exchange-specific behavior
  - SessionContextFactory: DIP-compliant factory for session context
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
from app.domain.ports.exchange_strategy import ExchangeStrategy
from app.domain.models.exchange_config import ExchangeConfig
from app.domain.services.symbol_registry import SymbolRegistry
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.fabio_ai.services.composite_profile import CompositeProfile
from app.domain.fabio_ai.services.alert_manager import AlertManager
from app.domain.fabio_ai.services.npoc_tracker import NPOCTracker
from app.domain.fabio_ai.services.session_context_factory import SessionContextFactory
from app.infrastructure.adapters.delta_profile_adapter import DeltaProfileAdapter

logger = logging.getLogger(__name__)


class ServiceGraph:
    """Holds the singleton service instances."""

    def __init__(self) -> None:
        self.event_bus = InMemoryEventBus()

        # ------------------------------------------------------------------
        # Exchange abstraction layer (OOP / SOLID / DDD)
        # ------------------------------------------------------------------
        # Load exchange configs — YAML overrides merged with defaults
        from config.consolidated import get_exchange_config

        self.exchange_config: ExchangeConfig = get_exchange_config(
            settings.DEFAULT_EXCHANGE
        )
        self.symbol_registry = SymbolRegistry.from_exchange_configs(
            {self.exchange_config.exchange: self.exchange_config}
        )

        # Strategy pattern — concrete strategy selected at startup
        if self.exchange_config.is_mcx():
            from app.infrastructure.strategies.mcx_strategy import MCXExchangeStrategy

            self.exchange_strategy: ExchangeStrategy = MCXExchangeStrategy(
                self.exchange_config
            )
        else:
            from app.infrastructure.strategies.nse_strategy import NSEExchangeStrategy

            self.exchange_strategy: ExchangeStrategy = NSEExchangeStrategy(
                self.exchange_config
            )

        # DIP-compliant session context factory
        self.session_factory = SessionContextFactory(
            exchange_config=self.exchange_config,
            symbol_registry=self.symbol_registry,
        )

        logger.info(
            "Exchange layer ready: exchange=%s, strategy=%s, underlyings=%s",
            self.exchange_config.exchange,
            type(self.exchange_strategy).__name__,
            sorted(self.exchange_config.underlyings),
        )

        # ------------------------------------------------------------------
        # Core adapters
        # ------------------------------------------------------------------
        self.market_data: MarketDataPort = DhanMarketDataAdapter(
            symbols=settings.DHAN_SYMBOLS,
            exchange=settings.DEFAULT_EXCHANGE,
            client_id=settings.DHAN_CLIENT_ID,
            access_token=settings.DHAN_ACCESS_TOKEN,
        )
        self.broker = PaperBrokerAdapter()
        self.llm_inference: LLMInferencePort = MLXInferenceAdapter(
            model_path=settings.MLX_MODEL_PATH,
            temperature=settings.LLM_TEMPERATURE,
            max_new_tokens=settings.LLM_MAX_NEW_TOKENS,
        )
        self.gen_ai_service = GenerativeAIService(
            llm_adapter=self.llm_inference,
            instruction=self.exchange_config.llm_instruction,
        )
        self._raw_storage = SQLiteStorageAdapter()
        # Wrap with async persistence bus — all writes go to background thread
        from app.infrastructure.async_persistence import AsyncPersistenceBus

        self._persistence_bus = AsyncPersistenceBus(self._raw_storage)
        self._persistence_bus.start()
        self.storage = self._persistence_bus  # TradingSessionService uses async writes

        # Probability engine (LightGBM first-passage models)
        _model_dir = os.path.join(os.path.dirname(__file__), "..", "..", "models")
        _model_dir = os.path.normpath(_model_dir)
        self.probability_engine: ProbabilityInferencePort = LGBMProbabilityAdapter(
            model_dir=_model_dir,
        )
        logger.info(
            "Probability engine ready=%s (model_dir=%s)",
            self.probability_engine.is_ready(),
            _model_dir,
        )

        # Composite Profile (Gap #4) — weekly bias from merged session profiles
        self.composite_profile = CompositeProfile(
            window=settings.COMPOSITE_SESSION_WINDOW
        )
        self._composite_cache: dict = {}

        # Alert Manager (Gap #6) — pre-alerts for Drive 1 returns
        self.alert_manager = AlertManager(
            proximity_ticks=settings.ALERT_PROXIMITY_TICKS,
        )

        # Delta Profile (Gap #1) — delta-colored volume profiles for entry zones
        from app.domain.constants import DELTA_BUCKET_SIZE_DEFAULT

        self.delta_profile = DeltaProfileAdapter(
            bucket_size=DELTA_BUCKET_SIZE_DEFAULT,
        )

        # VP Contract Selector — Volume Profile based contract selection
        from app.domain.fabio_ai.services.vp_contract_selector import VPContractSelector

        self.vp_contract_selector = VPContractSelector(
            broker=self.market_data,  # Use market data adapter for history
            exchange=self.exchange_config.exchange,
        )

        self.trading_session = TradingSessionService(
            event_bus=self.event_bus,
            broker=self.broker,
            gen_ai_service=self.gen_ai_service,
            storage=self.storage,
            probability_engine=self.probability_engine,
            exchange_config=self.exchange_config,
            allow_short=settings.ALLOW_SHORT,
        )
        # NPOC Tracker — naked POC tracking for secondary targets
        self.npoc_tracker = NPOCTracker(storage_port=self.storage)

        # Observability trackers (Phase -1)
        from app.domain.services.gate_rejection_tracker import GateRejectionTracker
        from app.domain.services.latency_tracker import LatencyTracker
        from app.api.routers.metrics import set_trackers

        self.gate_tracker = GateRejectionTracker()
        self.latency_tracker = LatencyTracker()
        set_trackers(self.gate_tracker, self.latency_tracker)

        # Pass trackers to session
        self.trading_session._gate_tracker = self.gate_tracker
        self.trading_session._latency_tracker = self.latency_tracker

        # OI Analyzer (Gap #5 — OI Pressure)
        from app.domain.fabio_ai.services.oi_analyzer import OIAnalyzer

        self.oi_analyzer = OIAnalyzer(market_data=self.market_data)

        # Signal Tracking Service — persists all gate decisions to DB
        from app.application.services.signal_tracking_service import (
            SignalTrackingService,
        )

        self.signal_tracker = SignalTrackingService(storage=self._raw_storage)

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
            logger.warning(
                "Broker pre-warm failed/timed out (non-critical — market may be closed)"
            )
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
                    top_per_underlying=settings.SCANNER_TOP_PER_UNDERLYING,
                    preferred_option_type=settings.SCANNER_OPTION_TYPE or None,
                    exchange=settings.DEFAULT_EXCHANGE,
                    expiry_index=settings.SCANNER_EXPIRY_INDEX,
                    strikes_around_atm=settings.STRIKES_AROUND_ATM,
                )

            _results = _scan_pool.submit(_scan).result(timeout=120)

            if _results:
                # Scanner found contracts with bullish momentum
                _final = [r for r in _results if r.ltp > 0]
                if not _final:
                    _final = _results
                self.active_symbols = [r.symbol for r in _final]
                for i, r in enumerate(_final, 1):
                    logger.info(
                        "Auto-selected #%d: %s (LTP=%.2f, OI=%d, Score=%.1f, Bias=%s)",
                        i,
                        r.symbol,
                        r.ltp,
                        r.oi,
                        r.score,
                        r.bias,
                    )
            else:
                # Scanner returned 0 — no bullish momentum
                # Still use DEFAULT_SYMBOL for data streaming (UI needs data)
                # But trade signals will be FLAT (no setups)
                logger.warning(
                    "No bullish setups found — using %s for data streaming (no trades)",
                    settings.DEFAULT_SYMBOL,
                )
        except (_cf.TimeoutError, Exception):
            logger.warning(
                "Option scanner failed/timed out — using DEFAULT_SYMBOL=%s",
                settings.DEFAULT_SYMBOL,
            )
        finally:
            _scan_pool.shutdown(wait=False)

        # VP-based contract selection (Volume Profile structure-driven)
        # Runs in parallel with the momentum scanner above
        _vp_scan_pool = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            from app.domain.fabio_ai.services.vp_contract_selector import (
                VPContractSelector as _VPCS,
            )

            def _vp_scan():
                _vp = _VPCS(
                    broker=self.market_data, exchange=self.exchange_config.exchange
                )
                return _vp.select_contracts()

            _vp_result = _vp_scan_pool.submit(_vp_scan).result(timeout=120)

            if _vp_result and _vp_result.total_contracts > 0:
                # Log VP-selected contracts
                for i, c in enumerate(_vp_result.candidates, 1):
                    logger.info(
                        "VP #%d: %s %s strike=%d entry=%.0f stop=%.0f "
                        "target=%.0f R:R=%.1f state=%s zone=%s",
                        i,
                        c.underlying,
                        c.option_type,
                        c.strike,
                        c.entry_price,
                        c.stop_price,
                        c.target_price,
                        c.rr_ratio,
                        c.market_state,
                        c.lvn_zone,
                    )

                # Log market states
                for idx, ms in _vp_result.market_states.items():
                    logger.info(
                        "VP State %s: %s (price=%.0f VAH=%.0f VAL=%.0f POC=%.0f)",
                        idx,
                        ms.state,
                        ms.price,
                        ms.vah,
                        ms.val,
                        ms.poc,
                    )

                # Store VP result for API access
                self.vp_result = _vp_result
            else:
                logger.info("VP selection: no contracts found (market may be closed)")
                self.vp_result = None

        except (_cf.TimeoutError, Exception) as e:
            logger.warning("VP contract selection failed: %s", e)
            self.vp_result = None
        finally:
            _vp_scan_pool.shutdown(wait=False)


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


# Exchange abstraction helpers


def get_exchange_config() -> ExchangeConfig:
    """Get the active exchange configuration."""
    return get_service_graph().exchange_config


def get_exchange_strategy() -> ExchangeStrategy:
    """Get the active exchange strategy (NSE or MCX)."""
    return get_service_graph().exchange_strategy


def get_symbol_registry() -> SymbolRegistry:
    """Get the symbol registry for exchange detection."""
    return get_service_graph().symbol_registry


def get_session_factory() -> SessionContextFactory:
    """Get the DIP-compliant session context factory."""
    return get_service_graph().session_factory


def get_vp_contract_selector():
    """Get the VP-based contract selector."""
    return get_service_graph().vp_contract_selector
