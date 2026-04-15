from typing import Type, Dict, Any, Optional, TypeVar, Generic, List, TYPE_CHECKING
import logging
from config.consolidated import ConsolidatedConfig as Configuration
import os

from app.domain.ports import (
    IMarketData,
    IBroker,
    IStorage,
    ILLMInference,
    IProbabilityInference,
    INotification,
    IDeltaProfile,
    INPOC,
    IExchangeStrategy,
)
from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter
from app.infrastructure.adapters.null_notification_adapter import (
    NullNotificationAdapter,
)
from app.infrastructure.adapters.delta_profile_adapter import DeltaProfileAdapter
from app.infrastructure.adapters.npoc_adapter import NPOCAdapter
from app.domain.services.amt_analysis_service import AMTAnalysisService
from app.domain.services.volume_profile_service import VolumeProfileService
from app.domain.services.lvn_analyzer import LVNAnalyzer
from app.domain.services.market_state_classifier import MarketStateClassifier
from app.domain.services.aggression_scorer import AggressionScorer
from app.domain.services.signal_generator import SignalGenerator
from app.domain.services.gate_pipeline import GatePipeline

# Stable port token for `is` checks inside `_create_service` (avoids UnboundLocalError
# if nested imports make the compiler treat `ILLMInference` as a local name).
_LLM_INFERENCE_PORT = ILLMInference

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceGraph:
    """Service graph for dependency injection and component management."""

    def __init__(self, config: Configuration):
        self._config = config
        self._services: Dict[Type, object] = {}
        self._adapters: Dict[Type, Type] = {}

        # Register default adapters
        self.register_adapter(IMarketData, DhanMarketDataAdapter)
        self.register_adapter(IBroker, PaperBrokerAdapter)
        self.register_adapter(IStorage, SQLiteStorageAdapter)

        # ILLMInference selection: choose between MLX and GGUF based on extension
        model_path = config.llm.model_path
        logger.info(
            f"ServiceGraph initializing ILLMInference: model_path='{model_path}'"
        )
        if model_path.lower().endswith(".gguf"):
            from app.infrastructure.adapters.gguf_inference_adapter import (
                GGUFInferenceAdapter,
            )

            self.register_adapter(ILLMInference, GGUFInferenceAdapter)
        else:
            from app.infrastructure.adapters.mlx_inference_adapter import (
                MLXInferenceAdapter,
            )

            self.register_adapter(ILLMInference, MLXInferenceAdapter)
        logger.info("ILLMInference adapter registered")

        self.register_adapter(IProbabilityInference, LGBMProbabilityAdapter)

        # Notification — null adapter (logs only; swap for Telegram/Slack adapter in prod)
        self.register_adapter(INotification, NullNotificationAdapter)

        # Delta volume profile
        self.register_adapter(IDeltaProfile, DeltaProfileAdapter)

        # NPOC tracking
        self.register_adapter(INPOC, NPOCAdapter)

        # Exchange strategy — select based on DEFAULT_EXCHANGE env / config
        exchange_mode = getattr(config, "default_exchange", None) or "MCX"
        if isinstance(exchange_mode, str):
            exchange_name = exchange_mode.upper()
        else:
            exchange_name = str(exchange_mode).upper()

        # NFO (NSE F&O segment) uses the same strategy stack as cash/index NSE
        if exchange_name in ("NSE", "NFO"):
            from app.infrastructure.strategies.nse_strategy import NSEExchangeStrategy

            self.register_adapter(IExchangeStrategy, NSEExchangeStrategy)
        else:
            # Default to MCX (project is configured for MCX commodity trading)
            from app.infrastructure.strategies.mcx_strategy import MCXExchangeStrategy

            self.register_adapter(IExchangeStrategy, MCXExchangeStrategy)

        # Initialize services (lazy initialization via get())
        # Populate active_symbols from config (dhan_symbols or fallback to settings)
        try:
            self._active_symbols: list = list(
                getattr(config, "dhan_symbols", None) or []
            )
        except Exception:
            self._active_symbols = []
        if not self._active_symbols:
            try:
                from app.config import settings as _settings

                self._active_symbols = list(
                    getattr(_settings, "DHAN_SYMBOLS", []) or []
                )
            except Exception:
                self._active_symbols = []

        # Eagerly create TradingSession so it's available for route handlers
        self._services["trading_session"] = self._create_trading_session()

    # ------------------------------------------------------------------
    # Property accessors — delegate to self.get() for lazy resolution
    # ------------------------------------------------------------------

    @property
    def storage(self) -> "IStorage":
        """Get storage service."""
        return self.get(IStorage)

    @property
    def llm_inference(self) -> "ILLMInference":
        """Get LLM inference service."""
        return self.get(ILLMInference)

    @property
    def probability_engine(self) -> "IProbabilityInference":
        """Get probability engine service."""
        return self.get(IProbabilityInference)

    @property
    def market_data(self) -> "IMarketData":
        """Get market data service."""
        return self.get(IMarketData)

    @property
    def trading_session(self):
        """Get trading session."""
        return self._services.get("trading_session", None)

    @property
    def active_symbols(self) -> list:
        """Get active symbols list.

        Returns the internal _active_symbols list, defaulting to empty list.
        """
        return getattr(self, "_active_symbols", [])

    @active_symbols.setter
    def active_symbols(self, value: list) -> None:
        """Set active symbols list (used by scanner rescan endpoint)."""
        self._active_symbols = list(value) if value is not None else []

    def _initialize_services(self) -> None:
        """Initialize services. Services are lazily created on demand via get()."""
        pass

    def _create_trading_session(self):
        """Create TradingSessionService with all required dependencies."""
        logger.info("Creating TradingSessionService...")
        try:
            # Import port types before TradingSessionService to avoid circular imports
            # touching get(ILLMInference) before the local `ILLMInference` name exists.
            from app.domain.ports import IBroker, IStorage
            from app.application.services.trading_session import TradingSessionService
            from app.domain.fabio_ai.services.generative_ai_service import (
                GenerativeAIService,
            )
            from app.domain.ports.probability_inference import NoOpProbabilityAdapter
            from app.config import settings as _settings

            logger.info("Getting broker adapter...")
            broker = self.get(IBroker)
            logger.info("Got broker, getting storage...")
            storage = self.get(IStorage)
            logger.info("Got storage, getting LLM adapter...")
            llm_adapter = self.get(_LLM_INFERENCE_PORT)
            logger.info(
                f"Got LLM adapter: {type(llm_adapter).__name__}, model_path={getattr(llm_adapter, 'model_path', None)}"
            )

            # Build GenerativeAIService wrapper around LLM adapter
            try:
                gen_ai_service = GenerativeAIService(llm_adapter=llm_adapter)
            except Exception:
                gen_ai_service = None

            # Exchange config
            try:
                from app.domain.models.exchange_config import ExchangeConfig

                exchange_name = getattr(self._config, "default_exchange", "MCX") or "MCX"
                ex = str(exchange_name).upper()
                if ex == "NFO":
                    ex = "NSE"
                exchange_config = ExchangeConfig.for_exchange(ex)
            except Exception:
                exchange_config = None

            # Probability engine
            try:
                from app.domain.ports import IProbabilityInference

                probability_engine = self.get(IProbabilityInference)
            except Exception:
                probability_engine = NoOpProbabilityAdapter()

            allow_short = bool(getattr(_settings, "ALLOW_SHORT", False))

            return TradingSessionService(
                broker=broker,
                gen_ai_service=gen_ai_service,
                storage=storage,
                probability_engine=probability_engine,
                exchange_config=exchange_config,
                allow_short=allow_short,
            )
        except Exception as e:
            import logging as _log

            _log.getLogger(__name__).error(
                "ServiceGraph: failed to create TradingSessionService: %s",
                e,
                exc_info=True,
            )
            return None

    def register_adapter(self, port: Type[T], implementation: Type[T]) -> None:
        """Register an adapter implementation for a port."""
        self._adapters[port] = implementation

    def get(self, service_type: Type[T]) -> T:
        """Retrieve a service instance."""
        if service_type not in self._services:
            self._services[service_type] = self._create_service(service_type)
        return self._services[service_type]

    def _create_service(self, service_type: Type) -> object:
        """Create a service instance with its dependencies."""
        # Scanner Service — dead code branch (ScannerService and its dependencies
        # IOptionChainFetcher, PremiumFilter, OIFilter, SpreadFilter, MomentumScorer,
        # TopNSelector are not implemented; kept here as a placeholder).
        # if service_type == ScannerService:
        #     return ScannerService(...)

        # Registered adapters (IMarketData, IBroker, IStorage, etc.) — checked FIRST
        # so adapter lookups are never blocked by optional service branches.
        if service_type in self._adapters:
            impl = self._adapters[service_type]

            # IExchangeStrategy implementations require an ExchangeConfig, not the
            # full ConsolidatedConfig. Build the correct ExchangeConfig here.
            if service_type is IExchangeStrategy:
                from app.domain.models.exchange_config import ExchangeConfig

                exchange_name = getattr(self._config, "default_exchange", "MCX") or "MCX"
                ex = str(exchange_name).upper()
                if ex == "NFO":
                    ex = "NSE"
                exc_config = ExchangeConfig.for_exchange(ex)
                return impl(exc_config)

            # IProbabilityInference requires a model directory path
            if service_type is IProbabilityInference:
                model_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "..", "..", "models"
                )
                model_dir = os.path.normpath(model_dir)
                try:
                    return impl(model_dir)
                except Exception:
                    # Fall back to NoOp if model files not found
                    from app.domain.ports.probability_inference import (
                        NoOpProbabilityAdapter,
                    )

                    return NoOpProbabilityAdapter()

            if service_type is _LLM_INFERENCE_PORT:
                llm = self._config.llm
                model_path = (llm.model_path or os.environ.get("MLX_MODEL_PATH", "")).strip()
                if impl.__name__ == "MLXInferenceAdapter":
                    return impl(
                        model_path=model_path,
                        temperature=llm.temperature,
                        max_new_tokens=llm.max_new_tokens,
                    )
                if impl.__name__ == "GGUFInferenceAdapter":
                    gp = (
                        llm.model_path
                        or os.environ.get("GGUF_MODEL_PATH", "")
                    ).strip()
                    return impl(model_path=gp)

            try:
                return impl()
            except TypeError:
                # Some adapters need config
                return impl(self._config)

        # AMT Analysis Service
        elif service_type == AMTAnalysisService:
            return AMTAnalysisService(
                volume_profile_service=self.get(VolumeProfileService),
                lvn_analyzer=self.get(LVNAnalyzer),
                market_state_classifier=self.get(MarketStateClassifier),
                aggression_scorer=self.get(AggressionScorer),
                signal_generator=self.get(SignalGenerator),
            )

        # Gate Pipeline
        elif service_type == GatePipeline:
            return GatePipeline(
                config=self._config,
                market_data=self.get(IMarketData),
                storage=self.get(IStorage),
                llm=self.get(_LLM_INFERENCE_PORT),
                probability=self.get(IProbabilityInference),
            )

        # SQLite storage (registered as IStorage, imported as SQLiteStorageAdapter)
        elif service_type.__name__ == "SQLiteStorageAdapter":
            from app.infrastructure.storage.database import SQLiteStorageAdapter

            return SQLiteStorageAdapter()

        # Configuration
        elif service_type == Configuration:
            return self._config

        # Generative AIService (needs ILLMInference from adapters)
        elif service_type.__name__ == "GenerativeAIService":
            from app.domain.fabio_ai.services.generative_ai_service import (
                GenerativeAIService,
            )

            llm_adapter = self.get(_LLM_INFERENCE_PORT)
            return GenerativeAIService(llm_adapter=llm_adapter)

        # Other services...

        raise ValueError(f"Unknown service type: {service_type}")

    # _create_scanner_filters removed — IContractFilter, PremiumFilter, OIFilter,
    # SpreadFilter are not yet implemented in this codebase.
