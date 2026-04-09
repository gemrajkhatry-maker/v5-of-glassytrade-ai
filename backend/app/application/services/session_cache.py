"""SessionCache — Manages cached analysis data and indicator snapshots.

Responsibilities:
- Store/retrieve AMT analysis results
- Store/retrieve footprint data
- Manage candle buffers and underlying data
- Cache invalidation and data retrieval for handlers
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult

log = logging.getLogger(__name__)

# Cap candle history per symbol to bound memory in long-running sessions.
MAX_CANDLES_PER_SYMBOL = 2000


class SessionCache:
    """Manages cached analysis data and indicator snapshots for a trading session.

    This class encapsulates all data caching logic that was previously scattered
    across TradingSession. It provides a clean API for:
    - Updating cached analysis results (AMT, footprint, etc.)
    - Retrieving latest cached data
    - Managing candle buffers
    - Invalidating stale data
    """

    def __init__(self, session_state: Any) -> None:
        """Initialize the cache with a reference to session state.

        Args:
            session_state: The SessionState instance to cache data for
        """
        self._session = session_state

    # ----- AMT Analysis Caching -----

    def update_amt(
        self,
        amt_result: AMTResult,
        amt_dto: dict,
        fp_dto: dict,
    ) -> None:
        """Update cached AMT analysis results.

        Args:
            amt_result: Full AMT result object
            amt_dto: AMT DTO for serialization
            fp_dto: Footprint DTO for serialization
        """
        with self._session._lock:
            self._session.last_amt = amt_dto
            self._session.last_footprint = fp_dto
            self._session._last_fp_domain = fp_dto
            self._session._last_aggressive_prints = amt_result.aggressive_prints

    def get_latest_amt(self) -> dict | None:
        """Get the latest AMT analysis result."""
        return self._session.last_amt

    def get_latest_footprint(self) -> dict | None:
        """Get the latest footprint data."""
        return self._session.last_footprint

    def get_fp_domain(self) -> dict | None:
        """Get the latest footprint domain data."""
        return getattr(self._session, "_last_fp_domain", None)

    def get_aggressive_prints(self) -> list | None:
        """Get the latest aggressive prints."""
        return getattr(self._session, "_last_aggressive_prints", None)

    # ----- AI Analysis Caching -----

    def update_ai_analysis(self, **kwargs) -> None:
        """Update cached AI analysis state.

        Args:
            **kwargs: AI analysis fields to update
        """
        self._session.update_ai_analysis(**kwargs)

    def get_ai_analysis(self) -> dict | None:
        """Get the latest AI analysis result."""
        return self._session.last_ai_analysis

    def set_ai_analysis(self, analysis: dict | None) -> None:
        """Set the AI analysis result directly."""
        self._session.last_ai_analysis = analysis

    # ----- Agent Decision Caching -----

    def set_agent_decision(self, decision: Any) -> None:
        """Cache the agent decision for execution on next candle."""
        self._session._agent_decision = decision

    def get_agent_decision(self) -> Any:
        """Get the cached agent decision."""
        return getattr(self._session, "_agent_decision", None)

    def set_pending_decision(
        self,
        decision: Any,
        amt_result: AMTResult | None = None,
        tick: OHLC | None = None,
    ) -> None:
        """Save pending decision for execution on next candle boundary.

        Args:
            decision: Agent decision to cache
            amt_result: AMT result at decision time
            tick: Tick at decision time
        """
        self._session._pending_decision = decision
        self._session._pending_amt = amt_result
        self._session._pending_tick = tick

    def get_pending_decision(self) -> tuple[Any, Any, Any]:
        """Get pending decision with associated AMT and tick.

        Returns:
            Tuple of (decision, amt_result, tick)
        """
        return (
            getattr(self._session, "_pending_decision", None),
            getattr(self._session, "_pending_amt", None),
            getattr(self._session, "_pending_tick", None),
        )

    def clear_pending_decision(self) -> None:
        """Clear the pending decision after execution."""
        with self._session._lock:
            self._session._pending_decision = None
            self._session._pending_amt = None
            self._session._pending_tick = None

    # ----- Candle Buffer Management -----

    def update_candle_buffer(self, tick: OHLC, storage=None, symbol: str = "") -> bool:
        """Update the candle buffer with a new tick.

        Args:
            tick: New OHLC tick
            storage: Optional storage for persisting closed candles
            symbol: Symbol for storage

        Returns:
            True if this is a new candle, False if updating existing
        """
        with self._session._lock:
            new_candle = not (self._session.data and self._session.data[-1].time == tick.time)
            if not new_candle:
                self._session.data[-1] = tick
            else:
                # Save closed candle to storage before appending new one
                if storage and self._session.data:
                    closed = self._session.data[-1]
                    try:
                        storage.save_tick(
                            symbol,
                            {
                                "time": closed.time,
                                "open": closed.open,
                                "high": closed.high,
                                "low": closed.low,
                                "close": closed.close,
                                "volume": closed.volume,
                                "delta": closed.delta,
                            },
                        )
                    except (OSError, Exception) as e:
                        log.warning("Failed to save tick for %s: %s", symbol, e, exc_info=True)
                self._session.data.append(tick)
                self._session._last_candle_time = tick.time
                # Bound memory
                if len(self._session.data) > MAX_CANDLES_PER_SYMBOL:
                    del self._session.data[: len(self._session.data) - MAX_CANDLES_PER_SYMBOL]
            return new_candle

    def get_data(self) -> list:
        """Get the candle data buffer."""
        return self._session.data

    def get_data_tuple(self) -> tuple:
        """Get the candle data as a tuple (for event passing)."""
        return tuple(self._session.data)

    # ----- Underlying Data Management -----

    def update_underlying_data(self, underlying_tick: OHLC | None) -> None:
        """Update the underlying futures data buffer.

        Args:
            underlying_tick: Underlying futures OHLC tick
        """
        if underlying_tick is None:
            return

        with self._session._lock:
            if not hasattr(self._session, "_underlying_data"):
                self._session._underlying_data = []
            ut = underlying_tick
            ut_new = not (
                self._session._underlying_data
                and self._session._underlying_data[-1].time == ut.time
            )
            if not ut_new:
                self._session._underlying_data[-1] = ut
            else:
                self._session._underlying_data.append(ut)
                if len(self._session._underlying_data) > MAX_CANDLES_PER_SYMBOL:
                    del self._session._underlying_data[
                        : len(self._session._underlying_data) - MAX_CANDLES_PER_SYMBOL
                    ]

    def get_underlying_data(self) -> list | None:
        """Get the underlying data buffer."""
        return getattr(self._session, "_underlying_data", None)

    def has_underlying_data(self, min_length: int = 20) -> bool:
        """Check if we have enough underlying data for analysis."""
        data = self.get_underlying_data()
        return data is not None and len(data) >= min_length

    # ----- Order Book Management -----

    def set_order_book(self, order_book: OrderBook | None) -> None:
        """Update the cached order book."""
        with self._session._lock:
            self._session.order_book = order_book

    def get_order_book(self) -> OrderBook | None:
        """Get the cached order book."""
        return self._session.order_book

    # ----- Pending Signal Management -----

    def set_pending_signal(self, symbol: str, signal: Any) -> None:
        """Set a pending signal for execution on next tick.

        Args:
            symbol: Symbol for the signal
            signal: Signal object
        """
        with self._session._lock:
            self._session._pending_signal = (symbol, signal)

    def drain_pending_signal(self) -> tuple[str, Any] | None:
        """Drain and return the pending signal.

        Returns:
            Tuple of (symbol, signal) or None
        """
        with self._session._lock:
            pending = self._session._pending_signal
            self._session._pending_signal = None
            return pending

    # ----- Timestamp Tracking -----

    def update_tick_time(self) -> None:
        """Update the last tick timestamp."""
        with self._session._lock:
            self._session._last_tick_time = time.time()

    def get_last_candle_time(self) -> str:
        """Get the last candle time."""
        return getattr(self._session, "_last_candle_time", "")

    def set_last_entry_candle_time(self, candle_time: str) -> None:
        """Set the last entry candle time for candle boundary tracking."""
        self._session._last_entry_candle_time = candle_time

    def get_last_entry_candle_time(self) -> str:
        """Get the last entry candle time."""
        return getattr(self._session, "_last_entry_candle_time", "")

    # ----- State Invalidation -----

    def invalidate(self) -> None:
        """Invalidate all cached data for a fresh start."""
        with self._session._lock:
            self._session.last_amt = None
            self._session.last_footprint = None
            self._session.last_prediction = None
            self._session.last_ai_analysis = None
            if hasattr(self._session, "_last_fp_domain"):
                self._session._last_fp_domain = None
            if hasattr(self._session, "_last_aggressive_prints"):
                self._session._last_aggressive_prints = None
            if hasattr(self._session, "_agent_decision"):
                self._session._agent_decision = None
            self._session._pending_decision = None
            self._session._pending_amt = None
            self._session._pending_tick = None

    # ----- Misc Cached Attributes -----

    def set_ib_state(self, ib_state: Any) -> None:
        """Cache the IB engine state."""
        self._session._ib_state = ib_state

    def get_ib_state(self) -> Any:
        """Get the cached IB engine state."""
        return getattr(self._session, "_ib_state", None)

    def set_llm_priority_score(self, score: float) -> None:
        """Cache the LLM priority score for UI display."""
        self._session._llm_priority_score = score

    def get_llm_priority_score(self) -> float:
        """Get the cached LLM priority score."""
        return getattr(self._session, "_llm_priority_score", 0.0)

    def set_last_session_info(self, session_info: Any) -> None:
        """Cache the last session info."""
        self._session._last_session_info = session_info

    def get_last_session_info(self) -> Any:
        """Get the cached session info."""
        return getattr(self._session, "_last_session_info", None)

    def set_last_exec_mono(self, mono_time: float) -> None:
        """Set the last execution monotonic time."""
        self._session._last_exec_mono = mono_time

    def get_last_exec_mono(self) -> float:
        """Get the last execution monotonic time."""
        return getattr(self._session, "_last_exec_mono", 0.0)

    def set_profile_saved(self, saved: bool = True) -> None:
        """Mark session profile as saved."""
        self._session._profile_saved = saved
