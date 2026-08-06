"""Tick Processor — Handles market data tick processing and routing.

Extracted from engine.py. Responsibilities:
- Tick demux and routing
- OI tracking and change calculation
- OrderBook depth building from packet data
- Throttled state updates between full process_tick calls
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from app.application.services.state_snapshot_builder import _camel_case_ai
from app.shared.depth_dto import order_book_to_dto

if TYPE_CHECKING:
    from app.application.candle_aggregator import CandleAggregator

logger = logging.getLogger(__name__)


class TickProcessor:
    """Processes incoming market data ticks.

    Handles:
    - OI (Open Interest) tracking and trend detection
    - OrderBook depth building from packet data
    - Throttled state updates between full process_tick calls
    """

    def __init__(
        self,
        candle_aggregator: "CandleAggregator",
    ):
        """Initialize tick processor.

        Args:
            candle_aggregator: Candle aggregator for footprint updates
        """
        self._candle_aggregator = candle_aggregator

        # Per-symbol state
        self._prev_oi_values: dict[str, int] = {}

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
        msg: dict = {
            "tick": ohlc_to_dto(tick),
            "ltp": ltp,
            "oi": oi,
            "_symbol": symbol,
            "depth": order_book_to_dto(current_depth),
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
                        "stopLoss": getattr(ad, "stop_loss", None),
                        "takeProfit": getattr(ad, "take_profit", None),
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
