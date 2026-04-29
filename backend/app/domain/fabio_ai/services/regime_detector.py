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
    price_zone: str = ""  # "ABOVE_VAH" | "BELOW_VAL" | "INSIDE_VA" | "AT_POC"
    poc: float = 0.0
    delta_sign: int = 0  # -1, 0, +1
    timestamp: float = 0.0


@dataclass(frozen=True)
class _FailedEntry:
    """Records a stopped-out entry for re-entry blocking (Fabio Rule 11)."""

    level: float
    direction: str  # "LONG" | "SHORT"
    session_phase: int  # session phase when the failure occurred


@dataclass(frozen=True)
class _LevelTouch:
    """Records when price approached a key level."""

    level: float
    timestamp: float
    retreated: bool = False  # True once price moved >0.5% away


@dataclass(frozen=True)
class SqueezeSignal:
    """Squeeze setup: trapped participants + recovery = entry catalyst."""

    direction: str  # "LONG" or "SHORT"
    trapped_level: float
    recovery_price: float


@dataclass
class ContractionConfig:
    """Tunable thresholds for contraction detection (Fabio Rule 8)."""

    contraction_ratio: float = (
        0.30  # current range < ratio * expansion range => contracting
    )
    lookback: int = 20  # candles to measure current range


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

        # Consecutive loss circuit breaker
        self._consecutive_stops: int = 0
        self._circuit_breaker_until: float = 0.0
        self.MAX_CONSECUTIVE_STOPS = 3
        self.CIRCUIT_BREAKER_SECONDS = 900.0  # 15-minute pause

        # Second drive tracking (Gap #6)
        self._level_touches: dict[float, _LevelTouch] = {}

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
            reasons.append(
                f"state: {self._previous.market_state} → {current.market_state}"
            )
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
            avg_delta = sum(list(self._recent_deltas)[:-1]) / (
                len(self._recent_deltas) - 1
            )
            if (
                avg_delta > 0
                and abs(tick.delta) > avg_delta * self.DELTA_SPIKE_MULTIPLIER
            ):
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
        expansion_window = data[-(lookback * 2) : -lookback]
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
                current_range,
                expansion_range,
                ratio * 100,
            )

        return is_contracted

    # ------------------------------------------------------------------
    # Fabio Rule 11 — Failed Auction Re-entry Blocking
    # ------------------------------------------------------------------

    def record_failed_entry(
        self, level: float, direction: str, session_phase: int
    ) -> None:
        """Record a stopped-out entry so the same level/direction is blocked.

        Call this when a position hits its stop loss.
        Also increments the consecutive stop counter for circuit breaker.
        """
        self._failed_entries.append(
            _FailedEntry(level=level, direction=direction, session_phase=session_phase)
        )
        # Cap to prevent unbounded growth in long sessions
        if len(self._failed_entries) > 50:
            self._failed_entries = self._failed_entries[-50:]

        # Consecutive loss circuit breaker
        self._consecutive_stops += 1
        if self._consecutive_stops >= self.MAX_CONSECUTIVE_STOPS:
            self._circuit_breaker_until = time.time() + self.CIRCUIT_BREAKER_SECONDS
            logger.warning(
                "CIRCUIT BREAKER: %d consecutive stops — pausing entries for %.0fs",
                self._consecutive_stops,
                self.CIRCUIT_BREAKER_SECONDS,
            )

        logger.info(
            "Recorded failed entry: level=%.2f dir=%s phase=%d (consecutive=%d)",
            level,
            direction,
            session_phase,
            self._consecutive_stops,
        )

    def record_successful_exit(self) -> None:
        """Reset consecutive stop counter on a profitable exit."""
        self._consecutive_stops = 0

    def is_circuit_breaker_active(self, current_time: float | None = None) -> bool:
        """Check if the circuit breaker is currently active."""
        now = current_time if current_time is not None else time.time()
        if now < self._circuit_breaker_until:
            remaining = self._circuit_breaker_until - now
            logger.info("Circuit breaker active — %.0fs remaining", remaining)
            return True
        # Once expired, reset the counter so next stop starts fresh
        if self._consecutive_stops >= self.MAX_CONSECUTIVE_STOPS:
            self._consecutive_stops = 0
        return False

    def is_re_entry_blocked(
        self,
        level: float,
        direction: str,
        session_phase: int,
        buffer_pct: float = 0.015,
        squeeze_active: bool = False,
        atr: float = 0.0,
    ) -> bool:
        """Check whether re-entry at *level* in *direction* is blocked.

        Re-entry is blocked when a previous stop-out occurred at the
        same level (within buffer) in the same direction during the
        same session phase.

        The buffer is the wider of:
        - *buffer_pct* (default 1.5%) of level price
        - 1x ATR (if provided)

        This wider buffer prevents repeated entries in the same failed
        price zone, which is critical for options where price clusters
        span 2-5% easily.

        Re-entry is allowed if:
        - A squeeze is active (trapped participants' forced exit IS the catalyst).
        - The session phase has changed (new structure).
        - The price is outside the buffer of all failed levels.
        """
        # Squeeze override: if squeeze detected at this level, ALLOW re-entry
        # Fabio: failed sellers' forced exit IS the entry catalyst
        if squeeze_active:
            return False

        # Compute absolute buffer distance: max of pct-based and ATR-based
        abs_buffer = level * buffer_pct
        if atr > 0:
            abs_buffer = max(abs_buffer, atr)

        for fe in self._failed_entries:
            if fe.direction != direction:
                continue
            if fe.session_phase != session_phase:
                continue  # new session phase — allow
            # Check if level is within buffer of the failed level
            if fe.level > 0 and abs(level - fe.level) <= abs_buffer:
                logger.info(
                    "Re-entry blocked: level=%.2f matches failed %.2f "
                    "(dir=%s phase=%d buffer=%.2f)",
                    level,
                    fe.level,
                    direction,
                    session_phase,
                    abs_buffer,
                )
                return True
        return False

    def clear_failed_entries(self) -> None:
        """Clear all failed entry records.  Call on new session start."""
        self._failed_entries.clear()
        self._consecutive_stops = 0
        self._circuit_breaker_until = 0.0
        logger.debug("Cleared failed entries and circuit breaker")

    # ------------------------------------------------------------------
    # Gap #6 — Second Drive Tracking
    # ------------------------------------------------------------------

    def record_level_approach(
        self, price: float, key_levels: list[float], timestamp: float
    ) -> None:
        """Record when price reaches within 0.3% of a key level."""
        for level in key_levels:
            if level <= 0:
                continue
            proximity = abs(price - level) / level
            bucket = round(level, 2)  # normalize to avoid float drift
            if proximity <= 0.003:  # within 0.3%
                if bucket not in self._level_touches:
                    self._level_touches[bucket] = _LevelTouch(
                        level=level, timestamp=timestamp
                    )
            elif proximity > 0.005 and bucket in self._level_touches:
                # Price moved >0.5% away — mark as retreated
                existing = self._level_touches[bucket]
                if not existing.retreated:
                    self._level_touches[bucket] = _LevelTouch(
                        level=existing.level,
                        timestamp=existing.timestamp,
                        retreated=True,
                    )
        # Cap to prevent unbounded growth in long sessions
        if len(self._level_touches) > 100:
            oldest_key = min(
                self._level_touches, key=lambda k: self._level_touches[k].timestamp
            )
            del self._level_touches[oldest_key]

    def is_second_drive(self, price: float, key_levels: list[float]) -> bool:
        """Check if price is re-approaching a level it already tested and retreated from."""
        for level in key_levels:
            if level <= 0:
                continue
            bucket = round(level, 1)
            touch = self._level_touches.get(bucket)
            if touch and touch.retreated:
                proximity = abs(price - level) / level
                if proximity <= 0.003:
                    return True
        return False

    # ------------------------------------------------------------------
    # Gap #7 — Squeeze Detection
    # ------------------------------------------------------------------

    def detect_squeeze(self, data: list, amt_result) -> SqueezeSignal | None:
        """Detect squeeze: ATR compression + failed level recovery.

        Fabio's primary live setup: trapped participants forced to cover = entry fuel.
        """
        if len(data) < 20:
            return None

        if not self.is_contracting(data):
            return None

        val = amt_result.value_area_low
        vah = amt_result.value_area_high

        if val <= 0 or vah <= 0:
            return None

        recent = data[-5:]
        current_price = data[-1].close

        # Long squeeze: price broke below VAL then recovered above it
        broke_low = any(c.low < val for c in recent)
        recovered_above = current_price > val
        if broke_low and recovered_above:
            return SqueezeSignal(
                direction="LONG", trapped_level=val, recovery_price=current_price
            )

        # Short squeeze: price broke above VAH then recovered below it
        broke_high = any(c.high > vah for c in recent)
        recovered_below = current_price < vah
        if broke_high and recovered_below:
            return SqueezeSignal(
                direction="SHORT", trapped_level=vah, recovery_price=current_price
            )

        return None

    def detect_bollinger_squeeze(self, data: list["OHLC"], period: int = 20) -> bool:
        """Bollinger Band squeeze: BB width < 10% of price = compression.

        When Bollinger Bands narrow significantly, it indicates low volatility
        and often precedes a sharp directional move (Fabio Rule 10: Momentum Squeeze).

        Args:
            data: OHLC candles for analysis.
            period: Lookback period for SMA/std (default 20).

        Returns:
            True if BB width < 10% of price (squeeze condition).
        """
        if len(data) < period:
            return False

        closes = [c.close for c in data[-period:]]
        sma = sum(closes) / period
        variance = sum((c - sma) ** 2 for c in closes) / period
        std = variance ** 0.5

        # BB width = (upper - lower) / sma = 4*std / sma
        if sma <= 0:
            return False
        bb_width = 4 * std / sma
        return bb_width < 0.10  # 10% of price = squeeze

    def is_atr_compressed(self, data: list["OHLC"], lookback: int = 20) -> bool:
        """ATR compression: current ATR < 50% of prior ATR.

        Measures whether recent volatility has compressed relative to
        the preceding period. Combined with Bollinger squeeze, this
        provides a volatility-independent confirmation of compression.

        Args:
            data: OHLC candles for analysis.
            lookback: Candles per ATR window (default 20).

        Returns:
            True if current ATR < 50% of prior period ATR.
        """
        required = lookback * 2
        if len(data) < required:
            return False

        recent_atr = self._compute_atr(data[-lookback:])
        prior_atr = self._compute_atr(data[-required:-lookback])

        if prior_atr <= 0:
            return False
        return recent_atr < 0.5 * prior_atr

    @staticmethod
    def _compute_atr(candles: list["OHLC"]) -> float:
        """Compute Average True Range for a list of candles."""
        if len(candles) < 2:
            return 0.0
        true_ranges = []
        prev_close = candles[0].close
        for c in candles[1:]:
            tr = max(
                c.high - c.low,
                abs(c.high - prev_close),
                abs(c.low - prev_close),
            )
            true_ranges.append(tr)
            prev_close = c.close
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    # ------------------------------------------------------------------
    # Follow-Through Analysis (Fabio)
    # ------------------------------------------------------------------

    def analyze_follow_through(
        self, data: list, break_direction: str, break_level: float
    ) -> dict | None:
        """Analyze if price continues or reverses after a bubble/break.

        After a big bubble breaks, track next 3 candles:
        - CONTINUATION: price keeps moving in break direction
        - REVERSAL: price reverses back toward/through break level
        - CONSOLIDATION: price stalls

        Returns dict with:
        - outcome: "CONTINUATION" | "REVERSAL" | "CONSOLIDATION"
        - strength: 0-1 confidence score
        """
        if len(data) < 5 or break_direction not in ("LONG", "SHORT"):
            return None

        # Get candles after the break (last 3 candles before current)
        post_break = data[-4:-1]  # 3 candles after break
        if len(post_break) < 3:
            return None

        if break_direction == "LONG":
            # Check if price continued up
            entry_price = post_break[0].close
            exit_price = post_break[-1].close
            continuation = exit_price > entry_price
            # Check if it reversed (went below break level)
            reversal = any(c.low < break_level for c in post_break)
        else:  # SHORT
            entry_price = post_break[0].close
            exit_price = post_break[-1].close
            continuation = exit_price < entry_price
            reversal = any(c.high > break_level for c in post_break)

        if continuation and not reversal:
            outcome = "CONTINUATION"
            strength = 0.8
        elif reversal:
            outcome = "REVERSAL"
            strength = 0.7
        else:
            outcome = "CONSOLIDATION"
            strength = 0.5

        return {"outcome": outcome, "strength": strength}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_snapshot(
        self, tick: OHLC, amt: AMTResult, now: float
    ) -> _RegimeSnapshot:
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
