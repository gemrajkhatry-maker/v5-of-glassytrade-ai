"""Session Context Factory — centralized session info retrieval.

Eliminates the duplicated pattern of market mapping + session info retrieval
that appears in 3+ locations throughout the codebase.

This factory accepts ExchangeConfig and SymbolRegistry via constructor
injection instead of importing app.config directly (DIP compliance).

Usage:
    factory = SessionContextFactory(exchange_config, symbol_registry)
    session_info = factory.from_tick(tick)
    exchange = factory.get_exchange_for_symbol("CRUDEOIL 19 MAR 6000 CALL")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from app.domain.fabio_ai.services.session_context import get_session_info
from app.domain.models.exchange_config import ExchangeConfig
from app.domain.services.symbol_registry import SymbolRegistry

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


class SessionContextFactory:
    """Factory for creating session context from tick data.

    DIP-compliant: receives config and registry via constructor.
    No infrastructure imports.
    """

    def __init__(
        self,
        exchange_config: ExchangeConfig,
        symbol_registry: Optional[SymbolRegistry] = None,
    ) -> None:
        self._config = exchange_config
        self._registry = symbol_registry or SymbolRegistry()

    @staticmethod
    def _normalize_market(market: str) -> str:
        """Normalize market identifier for session context.

        Maps NFO/BSE to NSE (same trading hours).
        """
        if market in ("NFO", "BSE"):
            return "NSE"
        return market

    def from_tick(
        self,
        tick: OHLC,
        market: str | None = None,
        open_price: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ):
        """Create session context from tick data.

        Args:
            tick: Current OHLC tick.
            market: Market identifier (defaults to injected config).
            open_price: Session open price (defaults to tick.open).
            prior_vah: Prior session VAH for gap analysis.
            prior_val: Prior session VAL for gap analysis.

        Returns:
            SessionInfo object with session phase, opening relation, etc.
        """
        effective_market: str = market if market is not None else self._config.exchange
        normalized_market = self._normalize_market(effective_market)
        effective_open = open_price if open_price > 0 else float(tick.open)

        return get_session_info(
            timestamp=tick.time,
            market=normalized_market,
            open_price=effective_open,
            prior_vah=prior_vah,
            prior_val=prior_val,
        )

    def from_settings(self, tick: OHLC, **kwargs):
        """Create session context using the injected exchange config."""
        return self.from_tick(tick, market=self._config.exchange, **kwargs)

    def get_exchange_for_symbol(self, symbol: str) -> str:
        """Determine exchange from symbol name using injected registry."""
        return self._registry.exchange_for(symbol)
