"""AMT Service — handles order flow and volume profile analysis.

Extracted from trading_session.py to separate AMT analysis logic
from the main trading pipeline.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from typing import Optional

from quant.contracts.value_objects import AMTResult
from quant.contracts.enums import MarketState
from app.application.handlers.amt_handler import AMTHandler

log = logging.getLogger(__name__)

# Lowered threshold from 20 to 5 candles — CVD on option data produces sign-flipping noise
# because option delta is driven by MM hedging, not actual market direction.
_UNDERLYING_MIN_CANDLES = 5


class AMTService:
    """Service for running AMT (Advanced Market Analysis) analysis."""

    def __init__(self, exchange: str = "MCX"):
        self._exchange = exchange
        self._latest_source_bars: dict[str, object | None] = {}
        # The auction source is pinned per symbol for the lifetime of a
        # trading session. This prevents a late futures warm-up from silently
        # changing the meaning of VWAP/CVD/profile state mid-session.
        self._source_by_symbol: dict[str, str] = {}
        self._amt_handlers: dict[str, AMTHandler] = {}
        self._underlying_state_cache: dict[str, tuple[float, str]] = {}
        self._underlying_state_ttl = 60.0  # seconds
        # Guards the _underlying_state_cache read-modify-write in
        # _sync_underlying_state (C6) — concurrent per-symbol ticks may sync.
        self._state_lock = threading.Lock()

    def _select_amt_data_source(
        self,
        cache,
        min_candles: int = 5,
        symbol: str | None = None,
    ) -> tuple[list, str]:
        """Select the AMT source, pinning it when a symbol is supplied.

        The unscoped form remains a compatibility helper for existing tests and
        callers. Production analysis always supplies ``symbol`` so source
        selection is stable for the whole session.
        """
        if symbol is not None and symbol in self._source_by_symbol:
            source = self._source_by_symbol[symbol]
            if source == "underlying":
                return cache.get_underlying_data(), source
            return cache.get_option_data(), source

        source = "underlying" if cache.has_underlying_data(min_candles) else "option"
        if symbol is not None:
            self._source_by_symbol[symbol] = source
        if source == "underlying":
            return cache.get_underlying_data(), source
        return cache.get_option_data(), source

    @staticmethod
    def _underlying_key(symbol: str) -> str:
        return symbol.split(" ")[0].split("-")[0].upper()

    def reset(self, symbol: str | None = None) -> None:
        """Reset source and cached AMT state at session rollover.

        Market state is shared by sibling options on one underlying. A single
        option rollover must not erase that shared state while another sibling
        remains active; it is cleared only after the final sibling resets.
        """
        symbols = [symbol] if symbol is not None else list(self._source_by_symbol)
        for target in symbols:
            underlying = self._underlying_key(target)
            self._source_by_symbol.pop(target, None)
            self._latest_source_bars.pop(target, None)
            self._amt_handlers.pop(target, None)
            sibling_active = any(
                self._underlying_key(active) == underlying
                for active in self._source_by_symbol
            )
            if not sibling_active:
                self._underlying_state_cache.pop(underlying, None)

    def latest_closed_bar(self, cache, symbol: str | None = None):
        """Return the exact source bar selected by the latest AMT analysis."""
        if symbol is not None and symbol in self._latest_source_bars:
            return self._latest_source_bars[symbol]
        amt_data, _ = self._select_amt_data_source(
            cache, _UNDERLYING_MIN_CANDLES, symbol=symbol
        )
        return amt_data[-1] if amt_data else None

    def run_analysis(
        self,
        event,
        session,
        cache,
        risk_coordinator,
        prior: Optional[dict] = None,
    ) -> Optional[AMTResult]:
        """Run AMT analysis with data source selection and prior profile injection."""
        # Select data source (underlying futures vs option premium) once. Clear
        # the previous selection first so an AMT failure cannot feed a stale bar
        # into the later quant decision stage.
        self._latest_source_bars[event.symbol] = None
        amt_data, cvd_source = self._select_amt_data_source(
            cache, _UNDERLYING_MIN_CANDLES, symbol=event.symbol
        )

        if cvd_source == "option":
            log.warning(
                "AMT: using option premium data for %s (no underlying futures available) "
                "— CVD/OFI will be from option ticks, not NIFTY FUT. Interpret with caution.",
                event.symbol,
            )

        # Initialize handler if needed
        if event.symbol not in self._amt_handlers:
            self._amt_handlers[event.symbol] = AMTHandler()

        srm = risk_coordinator.get_session_risk_manager(event.symbol)
        
        # Compute prior session average volume from prior profile
        prior_avg_volume = 0.0
        if prior:
            prior_total_vol = prior.get("total_volume", 0.0)
            prior_elapsed_min = prior.get("elapsed_minutes", 0.0)
            if prior_total_vol > 0 and prior_elapsed_min > 0:
                prior_avg_volume = prior_total_vol / prior_elapsed_min

        try:
            amt_result, amt_dto, fp_dto = self._amt_handlers[event.symbol].analyze(
                amt_data,
                event.order_book,
                prior_poc=prior.get("poc", 0.0) if prior else 0.0,
                prior_vah=prior.get("vah", 0.0) if prior else 0.0,
                prior_val=prior.get("val", 0.0) if prior else 0.0,
                cushion_tier=srm.risk_tier.name if srm else "NORMAL",
                session_pnl=srm.session_pnl if srm else 0.0,
                option_tick=event.tick,
                cvd_source=cvd_source,
                prior_avg_volume=prior_avg_volume,
            )
        except Exception:
            log.error(
                "AMT analysis failed for %s — skipping tick",
                event.symbol,
                exc_info=True,
            )
            return None

        self._latest_source_bars[event.symbol] = amt_data[-1] if amt_data else None

        # Update cache with AMT results
        cache.update_amt(amt_result, amt_dto, fp_dto)

        # Bug #4 fix: Share market state across options on the same underlying.
        amt_result = self._sync_underlying_state(event.symbol, amt_result, amt_dto)

        log.info(
            "AMT analysis done for %s: poc=%.2f vah=%.2f val=%.2f agg=%.2f ofi=%.3f cvd=%.1f state=%s ibH=%.2f ibL=%.2f",
            event.symbol,
            amt_dto.get("poc", 0),
            amt_dto.get("valueAreaHigh", 0),
            amt_dto.get("valueAreaLow", 0),
            amt_dto.get("aggression", 0),
            amt_dto.get("ofi", 0),
            amt_dto.get("cvdSlope", 0),
            amt_dto.get("marketState", "N/A"),
            amt_dto.get("ibHigh", 0),
            amt_dto.get("ibLow", 0),
        )

        return amt_result

    def _sync_underlying_state(self, symbol: str, amt_result, amt_dto) -> AMTResult:
        """Sync market state across options on the same underlying."""
        with self._state_lock:
            _underlying = self._underlying_key(symbol)
            _current_ms = amt_result.market_state
            _now = time.time()
            _cached = self._underlying_state_cache.get(_underlying)
            
            if _cached:
                _cached_ts, _cached_ms = _cached
                if (_now - _cached_ts) < self._underlying_state_ttl:
                    if _cached_ms != _current_ms:
                        log.info(
                            "Underlying state sync: %s overriding %s → %s (from sibling option)",
                            _underlying, _current_ms, _cached_ms,
                        )
                        _current_ms = _cached_ms
                        amt_result = dataclasses.replace(amt_result, market_state=_cached_ms)
                        amt_dto["marketState"] = _cached_ms
            
            self._underlying_state_cache[_underlying] = (_now, _current_ms)
            return amt_result

    def get_handler(self, symbol: str) -> AMTHandler:
        """Get or create AMT handler for symbol."""
        if symbol not in self._amt_handlers:
            self._amt_handlers[symbol] = AMTHandler()
        return self._amt_handlers[symbol]

    def create_sentinel_result(self) -> AMTResult:
        """Create a minimal sentinel AMTResult for error cases."""
        return AMTResult(
            market_state=MarketState.BALANCED.value,
            poc=0.0,
            value_area_high=0.0,
            value_area_low=0.0,
        )