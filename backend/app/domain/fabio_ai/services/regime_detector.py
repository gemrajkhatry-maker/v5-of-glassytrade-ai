"""Regime Detector — triggers LLM analysis on market state changes.

Instead of a fixed timer, the LLM is invoked only when meaningful
market regime changes occur: state transitions, VA boundary crossings,
POC migration shifts, or delta divergence spikes.
"""

from __future__ import annotations

import time
import logging
from collections import deque
from dataclasses import dataclass, field

from app.domain.trading.models.value_objects import AMTResult, OHLC

logger = logging.getLogger(__name__)

# Minimum cooldown between LLM invocations (seconds)
MIN_COOLDOWN = 5.0


@dataclass
class _RegimeSnapshot:
    """Captures the market state at a point in time."""
    market_state: str = ""
    price_zone: str = ""       # "ABOVE_VAH" | "BELOW_VAL" | "INSIDE_VA" | "AT_POC"
    poc: float = 0.0
    delta_sign: int = 0        # -1, 0, +1
    timestamp: float = 0.0


class RegimeDetector:
    """Detects meaningful market regime changes to trigger LLM analysis."""

    # POC migration threshold (relative change)
    POC_MIGRATION_THRESHOLD = 0.002  # 0.2%
    # Delta divergence threshold (absolute delta relative to price)
    DELTA_SPIKE_MULTIPLIER = 3.0

    def __init__(self) -> None:
        self._previous: _RegimeSnapshot | None = None
        self._last_trigger_time: float = 0.0
        self._recent_deltas: deque[float] = deque(maxlen=20)

    def should_trigger_llm(
        self,
        tick: OHLC,
        amt_result: AMTResult,
        current_time: float | None = None,
    ) -> bool:
        """Return True if the market regime has changed enough to warrant LLM analysis."""
        now = current_time if current_time is not None else time.time()

        # Always record delta history (even during cooldown) for spike detection
        self._recent_deltas.append(abs(tick.delta))

        # Enforce minimum cooldown
        if (now - self._last_trigger_time) < MIN_COOLDOWN:
            return False

        current = self._build_snapshot(tick, amt_result, now)

        # First observation — always trigger
        if self._previous is None:
            self._previous = current
            self._last_trigger_time = now
            return True

        triggered = False
        reasons: list[str] = []

        # 1. Market state transition (BALANCED ↔ IMBALANCED)
        if current.market_state != self._previous.market_state:
            reasons.append(f"state: {self._previous.market_state} → {current.market_state}")
            triggered = True

        # 2. VA boundary crossing
        if current.price_zone != self._previous.price_zone:
            reasons.append(f"zone: {self._previous.price_zone} → {current.price_zone}")
            triggered = True

        # 3. POC migration
        if self._previous.poc > 0:
            poc_change = abs(current.poc - self._previous.poc) / self._previous.poc
            if poc_change >= self.POC_MIGRATION_THRESHOLD:
                reasons.append(f"POC migrated {poc_change:.3%}")
                triggered = True

        # 4. Delta divergence spike
        if len(self._recent_deltas) >= 5:
            avg_delta = sum(list(self._recent_deltas)[:-1]) / (len(self._recent_deltas) - 1)
            if avg_delta > 0 and abs(tick.delta) > avg_delta * self.DELTA_SPIKE_MULTIPLIER:
                reasons.append(f"delta spike: {tick.delta:.0f} vs avg {avg_delta:.0f}")
                triggered = True

        if triggered:
            logger.debug("Regime change detected: %s", ", ".join(reasons))
            self._previous = current
            self._last_trigger_time = now

        return triggered

    def _build_snapshot(self, tick: OHLC, amt: AMTResult, now: float) -> _RegimeSnapshot:
        price = tick.close
        threshold = price * 0.001

        if price >= amt.value_area_high - threshold:
            zone = "ABOVE_VAH"
        elif price <= amt.value_area_low + threshold:
            zone = "BELOW_VAL"
        elif amt.poc > 0 and abs(price - amt.poc) < threshold:
            zone = "AT_POC"
        else:
            zone = "INSIDE_VA"

        return _RegimeSnapshot(
            market_state=amt.market_state,
            price_zone=zone,
            poc=amt.poc,
            delta_sign=1 if tick.delta > 0 else (-1 if tick.delta < 0 else 0),
            timestamp=now,
        )
