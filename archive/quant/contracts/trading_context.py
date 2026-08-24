"""TradingContext — Immutable context object passed through the trading pipeline.

Eliminates parameter clumps (amt_result, tick, order_book, session_info) that
appear in 8+ method signatures throughout the codebase.

Usage:
    ctx = TradingContext(
        tick=tick,
        amt_result=amt_result,
        order_book=order_book,
        session_info=session_info,
        agent_decision=agent_decision,
    )
    # Pass ctx instead of 4-5 separate parameters
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC, OrderBook, AMTResult
    from quant.amt.session.context import SessionInfo
    from quant.probability.agent_pipeline import AgentDecision


@dataclass(frozen=True)
class TradingContext:
    """Immutable trading context passed through the pipeline.

    Frozen dataclass prevents accidental mutation — all fields are read-only.
    This ensures the context is consistent throughout the processing chain.
    """

    tick: OHLC
    amt_result: AMTResult
    order_book: OrderBook | None = None
    session_info: SessionInfo | None = None
    agent_decision: AgentDecision | None = None

    @property
    def price(self) -> float:
        """Current price from tick."""
        return float(self.tick.close)

    @property
    def volume(self) -> float:
        """Current volume from tick."""
        return float(self.tick.volume)

    @property
    def delta(self) -> float:
        """Current delta from tick."""
        return float(self.tick.delta)

    @property
    def market_state(self) -> str:
        """Market state from AMT result."""
        return str(self.amt_result.market_state)

    @property
    def poc(self) -> float:
        """Point of Control from AMT result."""
        return float(self.amt_result.poc)

    @property
    def vah(self) -> float:
        """Value Area High from AMT result."""
        return float(self.amt_result.value_area_high)

    @property
    def val(self) -> float:
        """Value Area Low from AMT result."""
        return float(self.amt_result.value_area_low)

    @property
    def cvd_slope(self) -> float:
        """CVD slope from AMT result."""
        return float(self.amt_result.cvd_slope)

    @property
    def aggression(self) -> float:
        """Aggression score from AMT result."""
        return float(self.amt_result.aggression)

    @property
    def vwap(self) -> float:
        """Session VWAP from AMT result."""
        return float(self.amt_result.session_vwap) if self.amt_result.session_vwap > 0 else self.price

    @property
    def profile_shape(self) -> str:
        """Profile shape from AMT result."""
        return str(self.amt_result.profile_shape or "")

    @property
    def session_phase(self) -> str:
        """Session phase from session info."""
        if self.session_info is None:
            return ""
        return str(self.session_info.session or "")

    @property
    def opening_relation(self) -> str:
        """Opening relation from session info."""
        if self.session_info is None:
            return ""
        return str(self.session_info.opening_relation or "")

    @property
    def agent_direction(self) -> str:
        """Agent decision direction."""
        if self.agent_decision is None:
            return "FLAT"
        return str(self.agent_decision.direction or "FLAT")

    @property
    def agent_probability(self) -> float:
        """Agent decision probability."""
        if self.agent_decision is None:
            return 0.5
        return float(self.agent_decision.probability)

    @property
    def agent_regime(self) -> str:
        """Agent decision regime."""
        if self.agent_decision is None:
            return ""
        return str(self.agent_decision.regime or "")

    def with_tick(self, tick: OHLC) -> TradingContext:
        """Return a new context with updated tick (immutable)."""
        return TradingContext(
            tick=tick,
            amt_result=self.amt_result,
            order_book=self.order_book,
            session_info=self.session_info,
            agent_decision=self.agent_decision,
        )

    def with_agent_decision(self, agent_decision: AgentDecision | None) -> TradingContext:
        """Return a new context with updated agent decision (immutable)."""
        return TradingContext(
            tick=self.tick,
            amt_result=self.amt_result,
            order_book=self.order_book,
            session_info=self.session_info,
            agent_decision=agent_decision,
        )