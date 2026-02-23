"""Regime Detector — triggers LLM analysis on market state changes.

Instead of a fixed timer, the LLM is invoked only when meaningful
market regime changes occur: state transitions, VA boundary crossings,
POC migration shifts, or delta divergence spikes.

Also implements Fabio Rule 8 (contraction detection) and Rule 11
(failed auction re-entry blocking).
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


@dataclass(frozen=True)
class _FailedEntry:
    """Records a stopped-out entry for re-entry blocking (Fabio Rule 11)."""
    level: float
    direction: str        # "LONG" | "SHORT"
    session_phase: int    # session phase when the failure occurred


@dataclass
class ContractionConfig:
    """Tunable thresholds for contraction detection (Fabio Rule 8)."""
    contraction_ratio: float = 0.30   # current range < ratio * expansion range => contracting
    lookback: int = 20                # candles to measure current range


class RegimeDetector:
    """Detects meaningful market regime changes to trigger LLM analysis.

    Also provides:
    - Contraction detection (Fabio Rule 8): after expansion, detect when
      range compresses below 30% of the last expansion range.
    - Failed auction re-entry blocking (Fabio Rule 11): block re-entry
      at the same level/direction after a stop-out.
    """

    # POC migration threshold (relative change)
    POC_MIGRATION_THRESHOLD = 0.002  # 0.2%
    # Delta divergence threshold (absolute delta relative to price)
    DELTA_SPIKE_MULTIPLIER = 3.0

    def __init__(self, contraction_config: ContractionConfig | None = None) -> None:
        self._previous: _RegimeSnapshot | None = None
        self._last_trigger_time: float = 0.0
        self._recent_deltas: deque[float] = deque(maxlen=20)

        # Contraction detection state (Fabio Rule 8)
        self._config = contraction_config or ContractionConfig()

        # Failed auction re-entry state (Fabio Rule 11)
        self._failed_entries: list[_FailedEntry] = []

    # ------------------------------------------------------------------
    # LLM trigger detection (existing behaviour)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Fabio Rule 8 — Contraction Detection
    # ------------------------------------------------------------------

    def is_contracting(self, data: list[OHLC], lookback: int = 20) -> bool:
        """Detect contraction after expansion.

        Compares the range of the last *lookback* candles against the
        range of the preceding *lookback* candles (the expansion window).
        If the current range is less than ``contraction_ratio`` (default
        30%) of the expansion range, the market is contracting.

        When contracting, no new trend trades should be taken — only
        mean-reversion setups are valid.
        """
        if len(data) < lookback * 2:
            return False

        # Expansion window: candles before the current lookback window
        expansion_window = data[-(lookback * 2):-lookback]
        exp_high = max(c.high for c in expansion_window)
        exp_low = min(c.low for c in expansion_window)
        expansion_range = exp_high - exp_low

        if expansion_range <= 0:
            return False

        # Current window
        current_window = data[-lookback:]
        cur_high = max(c.high for c in current_window)
        cur_low = min(c.low for c in current_window)
        current_range = cur_high - cur_low

        ratio = current_range / expansion_range
        is_contracted = ratio < self._config.contraction_ratio

        if is_contracted:
            logger.debug(
                "Contraction detected: range=%.2f expansion=%.2f ratio=%.2f%%",
                current_range, expansion_range, ratio * 100,
            )

        return is_contracted

    # ------------------------------------------------------------------
    # Fabio Rule 11 — Failed Auction Re-entry Blocking
    # ------------------------------------------------------------------

    def record_failed_entry(self, level: float, direction: str, session_phase: int) -> None:
        """Record a stopped-out entry so the same level/direction is blocked.

        Call this when a position hits its stop loss.
        """
        self._failed_entries.append(
            _FailedEntry(level=level, direction=direction, session_phase=session_phase)
        )
        logger.info(
            "Recorded failed entry: level=%.2f dir=%s phase=%d",
            level, direction, session_phase,
        )

    def is_re_entry_blocked(
        self,
        level: float,
        direction: str,
        session_phase: int,
        buffer_pct: float = 0.003,
    ) -> bool:
        """Check whether re-entry at *level* in *direction* is blocked.

        Re-entry is blocked when a previous stop-out occurred at the
        same level (within *buffer_pct*) in the same direction during
        the same session phase.

        Re-entry is allowed if:
        - The session phase has changed (new structure).
        - The price is outside the buffer of all failed levels.
        """
        for fe in self._failed_entries:
            if fe.direction != direction:
                continue
            if fe.session_phase != session_phase:
                continue  # new session phase — allow
            # Check if level is within buffer of the failed level
            if fe.level > 0 and abs(level - fe.level) / fe.level <= buffer_pct:
                logger.debug(
                    "Re-entry blocked: level=%.2f matches failed %.2f (dir=%s phase=%d)",
                    level, fe.level, direction, session_phase,
                )
                return True
        return False

    def clear_failed_entries(self) -> None:
        """Clear all failed entry records.  Call on new session start."""
        self._failed_entries.clear()
        logger.debug("Cleared failed entries")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
