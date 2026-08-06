"""Drive Tracker — Level touch counting per Fabio AMT spec (FR-05).

Tracks how many times price has tested a key level (VAH, VAL, LVN) and
whether each test was rejected (wick + close opposite side).

Rules:
  D1 (First Drive): Market's initial push to a level — suppress entry.
  D1_REJECTED: Wick through level, close on opposite side — level holds.
  D2 (Second Drive): Re-approach after D1 rejection — valid entry zone.
  D2_NO_REJECTION: D1 wasn't rejected — still suppress (no edge).
  D3+: Third+ drive — level exhausted, suppress entry.

Momentum fade: D2 with lower volume/range than D1 = higher quality entry.
Session reset: All drives reset at session open (FR-05-08).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from quant.contracts.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass
class DriveState:
    """State of a single key level's drive history."""

    level: float
    direction: str  # "LONG" | "SHORT"
    drive_count: int = 0  # Number of touches
    d1_rejected: bool = False  # Was the first drive rejected?
    d1_volume: float = 0.0  # Volume at first drive (for momentum fade)
    d1_range: float = 0.0  # Range at first drive (for momentum fade)
    last_touch_time: str = ""


@dataclass
class DriveResult:
    """Result of drive classification."""

    drive_number: int  # 1, 2, or 3+
    entry_valid: bool  # True only for D2 with D1 rejected
    rejection_detected: bool
    fading_momentum: bool  # D2 has less volume/range than D1
    level: float
    reason: str


class DriveTracker:
    """Tracks touches at key levels per Fabio's drive methodology (FR-05).

    Usage:
        tracker = DriveTracker()
        result = tracker.classify_touch(price, level, candle, direction)
        if result.entry_valid:
            # D2 with D1 rejected — valid entry
    """

    # Rejection: wick through level must be > 50% of candle range
    REJECTION_WICK_RATIO = 0.5

    # Momentum fade: D2 volume/range < D1 volume/range × multiplier
    MOMENTUM_FADE_MULTIPLIER = 0.8

    def __init__(self, alert_manager=None) -> None:
        self._levels: dict[float, DriveState] = {}
        self._alert_manager = alert_manager

    def classify_touch(
        self,
        price: float,
        level: float,
        candle: OHLC,
        direction: str,
        tick_size: float = 0.05,
    ) -> DriveResult:
        """Classify the current touch of a key level.

        Args:
            price: Current price (should be near the level).
            level: The key level being tested.
            candle: Current candle (for rejection/wick detection).
            direction: "LONG" or "SHORT" — intended trade direction.

        Returns:
            DriveResult with drive number and entry validity.
        """
        from quant.contracts.tick_utils import round_to_tick

        bucket = round_to_tick(level, tick_size)

        # First touch of this level
        if bucket not in self._levels:
            rejected = self._detect_rejection(candle, level, direction)
            self._levels[bucket] = DriveState(
                level=level,
                direction=direction,
                drive_count=1,
                d1_rejected=rejected,
                d1_volume=float(candle.volume),
                d1_range=float(candle.high - candle.low),
                last_touch_time=candle.time,
            )
            logger.info(
                "D1 at level %.2f (dir=%s) rejected=%s",
                level,
                direction,
                rejected,
            )

            # Set alert on D1 for return to level (Gap #6)
            if self._alert_manager and rejected:
                try:
                    self._alert_manager.set_price_alert(
                        symbol=getattr(self, "_current_symbol", ""),
                        price=level,
                        direction=direction,
                        level_type="DRIVE_LEVEL",
                        tick_size=tick_size,
                    )
                except TypeError:
                    pass  # Drive level extraction error — non-critical
            return DriveResult(
                drive_number=1,
                entry_valid=False,  # D1 never valid
                rejection_detected=rejected,
                fading_momentum=False,
                level=level,
                reason="D1: first drive, entry suppressed",
            )

        state = self._levels[bucket]

        # Same direction — this is a re-touch
        if state.direction == direction:
            state.drive_count += 1

            # D2 check
            if state.drive_count == 2:
                if state.d1_rejected:
                    # QUANT SAFUGUARD: Enforce Time/Price Decay (FR-05-06)
                    from dateutil import parser

                    try:
                        t1 = parser.parse(state.last_touch_time)
                        t2 = parser.parse(candle.time)
                        time_decay_seconds = (t2 - t1).total_seconds()
                    except Exception:
                        time_decay_seconds = 180  # bypass if no time is provided

                    if time_decay_seconds < 180:
                        logger.info(
                            "D2 at level %.2f suppressed: insufficient time decay (%.0fs)",
                            level,
                            time_decay_seconds,
                        )
                        # Revert the count increment so it can still fire later
                        state.drive_count = 1
                        return DriveResult(
                            drive_number=2,
                            entry_valid=False,
                            rejection_detected=False,
                            fading_momentum=False,
                            level=level,
                            reason="D2: Insufficient time decay between touches (requires 3 minutes)",
                        )

                    # Check momentum fade
                    current_vol = float(candle.volume)
                    current_range = float(candle.high - candle.low)
                    fading = (
                        current_vol < state.d1_volume * self.MOMENTUM_FADE_MULTIPLIER
                        or current_range
                        < state.d1_range * self.MOMENTUM_FADE_MULTIPLIER
                    )
                    logger.info(
                        "D2 at level %.2f (dir=%s): D1 was rejected, entry valid, fading=%s",
                        level,
                        direction,
                        fading,
                    )
                    return DriveResult(
                        drive_number=2,
                        entry_valid=True,
                        rejection_detected=False,
                        fading_momentum=fading,
                        level=level,
                        reason="D2: second drive after rejection — valid entry",
                    )
                else:
                    logger.info(
                        "D2 at level %.2f (dir=%s): D1 NOT rejected, entry suppressed",
                        level,
                        direction,
                    )
                    return DriveResult(
                        drive_number=2,
                        entry_valid=False,
                        rejection_detected=False,
                        fading_momentum=False,
                        level=level,
                        reason="D2: D1 was not rejected — no edge",
                    )

            # D3+

            # Clear alerts for exhausted level (Gap #6)
            if self._alert_manager and state.drive_count >= 3:
                try:
                    self._alert_manager.clear_alerts_for_level(
                        getattr(self, "_current_symbol", ""), level
                    )
                except TypeError:
                    pass
            logger.info(
                "D%d at level %.2f (dir=%s): level exhausted, entry suppressed",
                state.drive_count,
                level,
                direction,
            )
            return DriveResult(
                drive_number=state.drive_count,
                entry_valid=False,
                rejection_detected=False,
                fading_momentum=False,
                level=level,
                reason=f"D{state.drive_count}: level exhausted — avoid",
            )

        # Different direction — treat as fresh D1
        rejected = self._detect_rejection(candle, level, direction)
        self._levels[bucket] = DriveState(
            level=level,
            direction=direction,
            drive_count=1,
            d1_rejected=rejected,
            d1_volume=float(candle.volume),
            d1_range=float(candle.high - candle.low),
            last_touch_time=candle.time,
        )
        logger.info(
            "D1 (direction change) at level %.2f (dir=%s) rejected=%s",
            level,
            direction,
            rejected,
        )
        return DriveResult(
            drive_number=1,
            entry_valid=False,
            rejection_detected=rejected,
            fading_momentum=False,
            level=level,
            reason="D1: direction change, entry suppressed",
        )

    def is_level_exhausted(self, level: float, tick_size: float = 0.05) -> bool:
        """Check if a level has been tested 3+ times (D3+)."""
        from quant.contracts.tick_utils import round_to_tick

        bucket = round_to_tick(level, tick_size)
        state = self._levels.get(bucket)
        return state is not None and state.drive_count >= 3

    def get_drive_count(self, level: float, tick_size: float = 0.05) -> int:
        """Get current drive count for a level."""
        from quant.contracts.tick_utils import round_to_tick

        bucket = round_to_tick(level, tick_size)
        state = self._levels.get(bucket)
        return state.drive_count if state else 0

    def set_current_symbol(self, symbol: str) -> None:
        """Set current symbol for alert tracking."""
        self._current_symbol = symbol

    def reset(self) -> None:
        """Reset all drive states. Call at session open (FR-05-08)."""
        self._levels.clear()
        logger.debug("Drive tracker reset (session open)")

    def _detect_rejection(
        self,
        candle: OHLC,
        level: float,
        direction: str,
    ) -> bool:
        """Detect rejection: wick through level, close on opposite side (FR-05-03)."""
        candle_range = float(candle.high - candle.low)
        if candle_range <= 0:
            return False

        if direction == "LONG":
            # For LONG: we're testing from below. Wick below level, close above.
            wick_below = float(candle.low) < level
            wick_size = level - float(candle.low)
            close_above = float(candle.close) > level
            return (
                wick_below
                and close_above
                and (wick_size / candle_range) > self.REJECTION_WICK_RATIO
            )
        else:
            # For SHORT: we're testing from above. Wick above level, close below.
            wick_above = float(candle.high) > level
            wick_size = float(candle.high) - level
            close_below = float(candle.close) < level
            return (
                wick_above
                and close_below
                and (wick_size / candle_range) > self.REJECTION_WICK_RATIO
            )
