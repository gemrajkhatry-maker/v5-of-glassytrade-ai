"""ServiceGraph V2 — thin wrapper around the DI Container.

This replaces the legacy ServiceGraph with an OCP-compliant implementation
that uses factory registration instead of an if/elif chain.

Backward-compatible: same public API as the original ServiceGraph.
"""

from __future__ import annotations

import logging
import os
from typing import Type, TypeVar

from config.config import Configuration

from app.application.di import DIContainer, compose_container
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

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceGraph:
    """Service graph backed by DIContainer.

    Drop-in replacement for the legacy ServiceGraph. Uses compose_container()
    to build the dependency graph, then resolves services via the container.

    Public API matches the original:
        - register_adapter(port, impl) — delegates to container
        - get(service_type) — delegates to container.resolve()
        - trading_session property — resolves TradingSessionService
        - active_symbols property — list of active symbols
    """

    def __init__(self, config: Configuration):
        self._config = config
        self._container = compose_container(config)

        # Additional adapters not in the base composition root
        self._register_additional_adapters()

        logger.info("ServiceGraph V2 initialized with DIContainer")

    def _register_additional_adapters(self) -> None:
        """Register adapters that are not in the base composition root."""
        # These are registered via the container but exposed through the
        # original register_adapter API for backward compatibility.
        pass

    def register_adapter(self, port: Type[T], implementation: Type[T]) -> None:
        """Register an adapter implementation for a port.

        Delegates to the DI container's factory registration.
        """
        self._container.register_singleton(
            port,
            lambda c, impl=implementation: impl(),
        )
        logger.debug("Adapter registered: %s -> %s", port.__name__, implementation.__name__)

    def get(self, service_type: Type[T]) -> T:
        """Retrieve a service instance."""
        return self._container.resolve(service_type)

    @property
    def storage(self) -> "IStorage":
        return self.get(IStorage)

    @property
    def llm_inference(self) -> "ILLMInference":
        return self.get(ILLMInference)

    @property
    def probability_engine(self) -> "IProbabilityInference":
        return self.get(IProbabilityInference)

    @property
    def market_data(self) -> "IMarketData":
        return self.get(IMarketData)

    @property
    def trading_session(self):
        from app.application.services.trading_session import TradingSessionService
        return self.get(TradingSessionService)

    @property
    def active_symbols(self) -> list:
        """Get active symbols list."""
        return list(getattr(self._config, "dhan_symbols", None) or [])

    @active_symbols.setter
    def active_symbols(self, value: list) -> None:
        """Set active symbols list."""
        if hasattr(self._config, "dhan_symbols"):
            self._config.dhan_symbols = list(value) if value else []

    @staticmethod
    def _is_live_mode() -> bool:
        env_mode = (os.getenv("GLASSYTRADE_ENV", "") or "").strip().lower()
        trading_mode = (os.getenv("TRADING_MODE", "") or "").strip().lower()
        return env_mode == "live" or trading_mode == "live"
