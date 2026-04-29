"""ServiceGraph — thin wrapper around DIContainer for backward compatibility.

All service resolution is delegated to the container built by
compose_container(). Property accessors preserve the legacy API
used by main.py, engine.py, and api/dependencies.py.
"""

from typing import Type, TypeVar, TYPE_CHECKING
import logging

from config.consolidated import ConsolidatedConfig as Configuration

from app.domain.ports import (
    IMarketData,
    IBroker,
    IStorage,
    ILLMInference,
    IProbabilityInference,
    INotification,
)

if TYPE_CHECKING:
    from app.application.services.trading_session import TradingSessionService

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Lazy type references to avoid circular imports at module load
_LLM_INFERENCE_PORT = ILLMInference


def _trading_session_type() -> Type["TradingSessionService"]:
    from app.application.services.trading_session import TradingSessionService
    return TradingSessionService


class ServiceGraph:
    """Thin wrapper around DIContainer for backward compatibility.

    All service resolution is delegated to the container built by
    compose_container(). Property accessors preserve the legacy API.
    """

    def __init__(self, config: Configuration):
        from app.application.di.composition_root import compose_container

        self._config = config
        self._container = compose_container(config)

        # Backward-compatible property accessors
        self._active_symbols: list = []
        try:
            self._active_symbols = list(getattr(config, "dhan_symbols", None) or [])
        except Exception:
            pass
        if not self._active_symbols:
            try:
                from app.config import settings as _settings
                self._active_symbols = list(getattr(_settings, "DHAN_SYMBOLS", []) or [])
            except Exception:
                self._active_symbols = []

        self._fut_to_options: dict[str, list[str]] = {}
        self._stream_symbols: list[str] = []

        # Eagerly resolve TradingSession so it's available for route handlers
        ts = self.get(_trading_session_type())
        if ts is None:
            raise RuntimeError(
                "TradingSessionService failed to initialize; refusing startup."
            )
        if hasattr(ts, "set_futures_option_map"):
            ts.set_futures_option_map(self._fut_to_options)

        # Wire observability trackers to metrics endpoint
        gate_tracker = getattr(ts, "_gate_tracker", None)
        latency_tracker = getattr(ts, "_latency_tracker", None)
        if gate_tracker and latency_tracker:
            try:
                from app.api.routers.metrics import set_trackers
                set_trackers(gate_tracker, latency_tracker)
            except Exception:
                logger.warning("Failed to wire metrics trackers — metrics endpoint will return errors", exc_info=True)

    @property
    def config(self) -> Configuration:
        return self._config

    @property
    def active_symbols(self) -> list:
        return self._active_symbols

    @active_symbols.setter
    def active_symbols(self, value: list) -> None:
        self._active_symbols = value

    @property
    def stream_symbols(self) -> list[str]:
        return self._stream_symbols

    @stream_symbols.setter
    def stream_symbols(self, value: list[str]) -> None:
        self._stream_symbols = value

    # Backward-compatible property accessors for commonly used services
    @property
    def trading_session(self):
        return self.get(_trading_session_type())

    @property
    def market_data(self):
        return self.get(IMarketData)

    @property
    def broker(self):
        return self.get(IBroker)

    @property
    def storage(self):
        return self.get(IStorage)

    @property
    def llm_inference(self):
        return self.get(_LLM_INFERENCE_PORT)

    @property
    def probability_engine(self):
        return self.get(IProbabilityInference)

    @property
    def notification(self):
        return self.get(INotification)

    @property
    def engine(self):
        """TradingEngine — set by main.py after construction."""
        return getattr(self, "_engine", None)

    @engine.setter
    def engine(self, value) -> None:
        self._engine = value

    def get(self, service_type: Type[T]) -> T:
        """Retrieve a service instance from the DI container."""
        try:
            return self._container.resolve(service_type)
        except Exception:
            return None
