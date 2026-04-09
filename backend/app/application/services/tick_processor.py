"""Tick Processor — Handles market data tick processing and routing.

Extracted from engine.py. Responsibilities:
- Tick demux and routing
- OI tracking and change calculation
- OrderBook depth building from packet data
- Range bar builder updates
- Throttled state updates between full process_tick calls
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel

if TYPE_CHECKING:
    from app.application.candle_aggregator import CandleAggregator
    from app.application.range_bar_builder import RangeBarBuilder

logger = logging.getLogger(__name__)


class TickProcessor:
    """Processes incoming market data ticks.

    Handles:
    - OI (Open Interest) tracking and trend detection
    - OrderBook depth building from packet data
    - Range bar builder coordination
    - Throttled state updates between full process_tick calls
    """

    def __init__(
        self,
        candle_aggregator: "CandleAggregator",
        range_default_size: float = 3.0,
    ):
        """Initialize tick processor.

        Args:
            candle_aggregator: Candle aggregator for footprint updates
            range_default_size: Default range size for range bars (points)
        """
        self._candle_aggregator = candle_aggregator
        self._range_default_size = range_default_size

        # Per-symbol state
        self._prev_oi_values: dict[str, int] = {}
        self._range_builders: dict[str, RangeBarBuilder] = {}

    # ------------------------------------------------------------------
    # OI Tracking
    # ------------------------------------------------------------------

    def track_oi(self, symbol: str, oi: int) -> dict | None:
        """Track OI changes and return OI data dict.

        Args:
            symbol: Trading symbol
            oi: Current open interest

        Returns:
            OI data dict with oi, oi_change, oi_trend or None if oi <= 0
        """
        if oi <= 0:
            return None

        prev_oi = self._prev_oi_values.get(symbol, 0)
        oi_change = oi - prev_oi if prev_oi > 0 else 0
        self._prev_oi_values[symbol] = oi

        return {
            "oi": oi,
            "oi_change": oi_change,
            "oi_trend": "RISING"
            if oi_change > 0
            else ("FALLING" if oi_change < 0 else "FLAT"),
        }

    def get_prev_oi(self, symbol: str) -> int:
        """Get previous OI value for a symbol."""
        return self._prev_oi_values.get(symbol, 0)

    # ------------------------------------------------------------------
    # OrderBook Depth Building
    # ------------------------------------------------------------------

    def build_depth_from_packet(
        self,
        symbol: str,
        current_book: OrderBook | None,
        pkt_bids: list[dict],
        pkt_asks: list[dict],
    ) -> OrderBook | None:
        """Build or update OrderBook from packet data.

        Args:
            symbol: Trading symbol
            current_book: Current order book (may be None or shallow)
            pkt_bids: Bid levels from packet
            pkt_asks: Ask levels from packet

        Returns:
            Updated OrderBook or None if no data
        """
        if not pkt_bids and not pkt_asks:
            return current_book

        is_shallow = (
            current_book is None
            or len(current_book.bids) < 10
            or len(current_book.asks) < 10
        )

        if is_shallow:
            return OrderBook(
                bids=tuple(
                    OrderBookLevel(
                        price=float(b.get("price", 0)),
                        quantity=float(b.get("qty", 0)),
                    )
                    for b in pkt_bids
                ),
                asks=tuple(
                    OrderBookLevel(
                        price=float(a.get("price", 0)),
                        quantity=float(a.get("qty", 0)),
                    )
                    for a in pkt_asks
                ),
            )

        return current_book

    # ------------------------------------------------------------------
    # Range Bar Builder
    # ------------------------------------------------------------------

    def get_or_create_range_builder(
        self, symbol: str, range_size: float | None = None
    ) -> "RangeBarBuilder":
        """Get or create a range bar builder for a symbol.

        Args:
            symbol: Trading symbol
            range_size: Range size (uses default if None)

        Returns:
            RangeBarBuilder instance
        """
        if symbol not in self._range_builders:
            from app.application.range_bar_builder import RangeBarBuilder

            size = range_size or self._range_default_size
            self._range_builders[symbol] = RangeBarBuilder(range_size=size)
        return self._range_builders[symbol]

    def update_range_bar(
        self,
        symbol: str,
        ltp: float,
        timestamp: str,
        tick: OHLC,
    ) -> dict | None:
        """Update range bar builder with new tick.

        Args:
            symbol: Trading symbol
            ltp: Last traded price
            timestamp: Tick timestamp
            tick: OHLC tick for volume split

        Returns:
            Range bar dict for state broadcast, or None if no builder
        """
        rb = self._range_builders.get(symbol)
        if rb is None:
            return None

        rb.on_tick(
            ltp=float(ltp),
            timestamp=timestamp,
            buy_vol=float(tick.taker_buy_volume),
            sell_vol=max(0.0, float(tick.volume) - float(tick.taker_buy_volume)),
        )
        return rb.to_dict()

    def backfill_range_bars(
        self, symbol: str, session_data: list[OHLC], limit: int = 200
    ) -> None:
        """Backfill range bars from historical candle data.

        Generates synthetic ticks from each historical candle's OHLC
        so the range bar builder has initial data.

        Args:
            symbol: Trading symbol
            session_data: List of historical OHLC candles
            limit: Maximum number of candles to process
        """
        rb = self._range_builders.get(symbol)
        if not rb or not session_data:
            return

        try:
            for candle in session_data[-limit:]:
                ts = str(candle.time) if hasattr(candle, "time") else ""
                o = float(candle.open)
                h = float(candle.high)
                l = float(candle.low)
                c = float(candle.close)
                v = float(candle.volume)
                tb = float(getattr(candle, "taker_buy_volume", v / 2))

                if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                    continue

                # Generate synthetic ticks: open → low → high → close
                ticks = [o]
                if l < o:
                    ticks.append(l)
                if h > o:
                    ticks.append(h)
                ticks.append(c)

                vol_per_tick = v / len(ticks) if ticks else 0
                buy_per_tick = tb / len(ticks) if ticks else 0
                sell_per_tick = (v - tb) / len(ticks) if ticks else 0

                for tick_price in ticks:
                    rb.on_tick(
                        ltp=tick_price,
                        timestamp=ts,
                        buy_vol=buy_per_tick,
                        sell_vol=sell_per_tick,
                    )
        except Exception:
            pass  # Non-critical — depth book degrades gracefully

    def get_range_builder_dict(self, symbol: str) -> dict | None:
        """Get range bar dict for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Range bar dict or None
        """
        rb = self._range_builders.get(symbol)
        return rb.to_dict() if rb else None

    # ------------------------------------------------------------------
    # Throttled State Update
    # ------------------------------------------------------------------

    def build_throttled_state(
        self,
        symbol: str,
        tick: OHLC,
        ltp: float,
        oi: int,
        current_depth: OrderBook | None,
        session,
        session_service,
        ohlc_to_dto,
    ) -> dict:
        """Build partial state update between full process_tick calls.
        
        Uses _camel_case_ai from state_snapshot_builder for consistent DTO formatting.
        """
        from app.application.engine import _depth_to_dto
        from app.application.services.state_snapshot_builder import _camel_case_ai

        msg: dict = {
            "tick": ohlc_to_dto(tick),
            "ltp": ltp,
            "oi": oi,
            "_symbol": symbol,
            "depth": _depth_to_dto(current_depth),
        }

        try:
            if session:
                if session.last_ai_analysis:
                    msg["genAIAnalysis"] = _camel_case_ai(
                        session.last_ai_analysis
                    )
                if session.last_amt:
                    msg["amt"] = session.last_amt
                if hasattr(session, "_agent_decision") and session._agent_decision:
                    ad = session._agent_decision
                    msg["agentDecision"] = {
                        "direction": ad.direction,
                        "probability": ad.probability,
                        "regime": ad.regime,
                        "timing": ad.timing,
                        "sizeFraction": ad.size_fraction,
                        "slAdjust": ad.sl_adjust,
                        "tpAdjust": ad.tp_adjust,
                        "latencyUs": ad.latency_us,
                        "rationale": ad.rationale,
                    }
        except Exception:
            logger.debug("Exception handled silently", exc_info=True)

        return msg

    # ------------------------------------------------------------------
    # Symbol Management
    # ------------------------------------------------------------------

    def initialize_symbol(self, symbol: str) -> None:
        """Initialize state for a new symbol.

        Args:
            symbol: Trading symbol to initialize
        """
        self._prev_oi_values[symbol] = 0

    def remove_symbol(self, symbol: str) -> None:
        """Remove all state for a symbol.

        Args:
            symbol: Trading symbol to remove
        """
        self._prev_oi_values.pop(symbol, None)
        self._range_builders.pop(symbol, None)
