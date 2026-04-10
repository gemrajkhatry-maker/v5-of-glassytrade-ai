"""Auction State Machine — deterministic state transitions with guards.

States: NO_TRADE → BALANCED ↔ PROBING ↔ IMBALANCED

Transition rules (hysteresis to prevent oscillation):
  NO_TRADE → BALANCED  : price moves outside POC dead zone
  NO_TRADE → PROBING   : price outside VA
  BALANCED → PROBING   : price outside VA edge with displacement
  BALANCED → IMBALANCED: price outside VA + displacement + acceptance
  PROBING → IMBALANCED : displacement + acceptance confirmed
  PROBING → BALANCED   : price re-enters VA
  IMBALANCED → BALANCED: price returns to VA + 2+ candles inside
  IMBALANCED → PROBING : price outside VA but acceptance lost
"""

from __future__ import annotations

import logging
from appv2.domain.enums.market_state import MarketState
from appv2.config import constants as C

logger = logging.getLogger(__name__)


# Valid transitions map
_VALID_TRANSITIONS: dict[MarketState, set[MarketState]] = {
    MarketState.NO_TRADE: {MarketState.BALANCED, MarketState.PROBING, MarketState.IMBALANCED},
    MarketState.BALANCED: {MarketState.PROBING, MarketState.IMBALANCED, MarketState.NO_TRADE},
    MarketState.PROBING: {MarketState.IMBALANCED, MarketState.BALANCED, MarketState.NO_TRADE},
    MarketState.IMBALANCED: {MarketState.BALANCED, MarketState.PROBING},
}


class AuctionStateMachine:
    """Tracks auction state with hysteresis and transition guards."""

    def __init__(self, initial: MarketState = MarketState.NO_TRADE):
        self._state = initial
        self._previous: MarketState | None = None
        self._transition_count: dict[str, int] = {}
        # Hysteresis counters
        self._balanced_count: int = 0  # Candles inside VA (for IMBALANCED→BALANCED)
        self._outside_count: int = 0  # Candles outside VA (for BALANCED→PROBING)

    def evaluate(
        self,
        price: float,
        poc: float,
        vah: float,
        val: float,
        tick_size: float,
        has_displacement: bool,
        has_acceptance: bool,
        balance_ratio: float = 0.0,
    ) -> MarketState:
        """Evaluate and potentially transition state.

        Returns the (possibly new) state.
        """
        from appv2.domain.services.market_state_engine import detect_market_state

        raw = detect_market_state(
            price, poc, vah, val, tick_size,
            has_displacement, has_acceptance, balance_ratio,
        )
        proposed = raw.state

        # Hysteresis: IMBALANCED → BALANCED requires 2+ candles inside VA
        if self._state == MarketState.IMBALANCED and proposed == MarketState.BALANCED:
            if val <= price <= vah:
                self._balanced_count += 1
            else:
                self._balanced_count = 0
            if self._balanced_count < 2:
                return self._state  # Hold IMBALANCED

        # Hysteresis: BALANCED → PROBING at edge requires persistent signal
        if self._state == MarketState.BALANCED and proposed == MarketState.PROBING:
            if price > vah or price < val:
                self._outside_count += 1
            else:
                self._outside_count = 0
            if self._outside_count < 2:
                return self._state  # Hold BALANCED

        # Validate transition
        if proposed != self._state and self._is_valid_transition(self._state, proposed):
            self._log_transition(self._state, proposed, raw.trigger)
            self._previous = self._state
            self._state = proposed
            self._balanced_count = 0
            self._outside_count = 0
            key = f"{self._previous.value}->{self._state.value}"
            self._transition_count[key] = self._transition_count.get(key, 0) + 1

        return self._state

    @property
    def state(self) -> MarketState:
        return self._state

    @property
    def previous(self) -> MarketState | None:
        return self._previous

    def reset(self, initial: MarketState = MarketState.NO_TRADE) -> None:
        self._state = initial
        self._previous = None
        self._balanced_count = 0
        self._outside_count = 0

    @staticmethod
    def _is_valid_transition(from_state: MarketState, to_state: MarketState) -> bool:
        return to_state in _VALID_TRANSITIONS.get(from_state, set())

    @staticmethod
    def _log_transition(from_state: MarketState, to_state: MarketState, reason: str) -> None:
        logger.info(
            "State transition: %s → %s | %s",
            from_state.value, to_state.value, reason,
        )
