"""Session Context Factory — centralized session info retrieval.

Eliminates the duplicated pattern of market mapping + session info retrieval
that appears in 3+ locations throughout the codebase.

Usage:
    session_info = SessionContextFactory.from_tick(tick, market="MCX")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import Settings
from app.domain.fabio_ai.services.session_context import get_session_info

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


class SessionContextFactory:
    """Factory for creating session context from tick data.

    Handles the common pattern:
        _market = Settings().DEFAULT_EXCHANGE
        if _market in ("NFO", "BSE"): _market = "NSE"
        session_info = get_session_info(timestamp=tick.time, market=_market)
    """

    @staticmethod
    def _normalize_market(market: str) -> str:
        """Normalize market identifier for session context.

        Maps NFO/BSE to NSE (same trading hours).
        """
        if market in ("NFO", "BSE"):
            return "NSE"
        return market

    @staticmethod
    def from_tick(
        tick: OHLC,
        market: str | None = None,
        open_price: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ):
        """Create session context from tick data.

        Args:
            tick: Current OHLC tick.
            market: Market identifier (defaults to Settings.DEFAULT_EXCHANGE).
            open_price: Session open price (defaults to tick.open).
            prior_vah: Prior session VAH for gap analysis.
            prior_val: Prior session VAL for gap analysis.

        Returns:
            SessionInfo object with session phase, opening relation, etc.
        """
        if market is None:
            market = Settings().DEFAULT_EXCHANGE

        normalized_market = SessionContextFactory._normalize_market(market)
        effective_open = open_price if open_price > 0 else float(tick.open)

        return get_session_info(
            timestamp=tick.time,
            market=normalized_market,
            open_price=effective_open,
            prior_vah=prior_vah,
            prior_val=prior_val,
        )

    @staticmethod
    def from_settings(tick: OHLC, **kwargs):
        """Create session context using default exchange from settings.

        Convenience method that uses Settings().DEFAULT_EXCHANGE.
        """
        return SessionContextFactory.from_tick(
            tick,
            market=Settings().DEFAULT_EXCHANGE,
            **kwargs,
        )

    @staticmethod
    def get_exchange_for_symbol(symbol: str) -> str:
        """Determine exchange from symbol name.

        Args:
            symbol: Trading symbol (e.g., "CRUDEOIL 17 MAR 6100 CALL").

        Returns:
            Exchange identifier ("NSE", "MCX", etc.).
        """
        _MCX_UNDERLYINGS = {"CRUDEOIL", "GOLD", "SILVER", "NATURALGAS", "COPPER"}
        _NSE_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY"}

        clean = symbol.replace("NSE:", "").replace("MCX:", "").strip()
        underlying = clean.split("-")[0].split(" ")[0].upper()

        if underlying in _MCX_UNDERLYINGS:
            return "MCX"
        if underlying in _NSE_UNDERLYINGS:
            return "NSE"

        # Fallback to settings default
        return Settings().DEFAULT_EXCHANGE