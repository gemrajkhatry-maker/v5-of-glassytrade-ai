"""Session context factory for tick-driven session metadata."""
from __future__ import annotations

from app.domain.fabio_ai.services.session_context import SessionInfo, get_session_info


class SessionContextFactory:
    def __init__(self, exchange: str = "NSE", symbol_registry=None) -> None:
        self._exchange = exchange
        self._registry = symbol_registry

    @staticmethod
    def _normalize_market(market: str) -> str:
        if market in {"NFO", "BSE"}:
            return "NSE"
        return market

    def from_tick(self, tick, market: str | None = None, open_price: float = 0.0, prior_vah: float = 0.0, prior_val: float = 0.0) -> SessionInfo:
        effective_market = self._normalize_market((market or self._exchange).upper())
        return get_session_info(
            timestamp=tick.time,
            market=effective_market,
            open_price=open_price if open_price > 0 else float(getattr(tick, "open", 0.0)),
            prior_vah=prior_vah,
            prior_val=prior_val,
        )

    def from_settings(self, tick, **kwargs):
        return self.from_tick(tick, market=self._exchange, **kwargs)

    def get_exchange_for_symbol(self, symbol: str) -> str:
        if self._registry is not None and hasattr(self._registry, "exchange_for"):
            return self._registry.exchange_for(symbol)
        if symbol.endswith("M") or symbol.upper() in {"GOLD", "SILVER", "CRUDEOIL"}:
            return "MCX"
        return self._exchange
