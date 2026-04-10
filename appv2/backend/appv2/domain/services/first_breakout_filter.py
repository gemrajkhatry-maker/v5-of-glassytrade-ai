"""First Breakout Filter — avoids fake breakouts.

Fabio's rule: *"I don't take the first movement. I wait for the first breakout.
I get clear market participants of what they want to do. I don't risk that this
is only a retracement and then they collapse."*

This filter:
1. Detects the first VA break attempt
2. Waits for confirmation (2+ candles beyond VA + volume)
3. Only allows entries AFTER the first breakout is confirmed
4. Tracks failed breakouts separately (mean reversion setups)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BreakoutState(str, Enum):
    NO_ATTEMPT = "NO_ATTEMPT"
    FIRST_ATTEMPT = "FIRST_ATTEMPT"
    FIRST_FAILED = "FIRST_FAILED"
    CONFIRMED_BREAKOUT = "CONFIRMED_BREAKOUT"
    RE_TESTING = "RE_TESTING"


@dataclass(frozen=True)
class BreakoutStatus:
    state: BreakoutState
    direction: str  # "UP" | "DOWN" | ""
    attempt_count: int
    confirmation_bars: int
    failed_at_level: float = 0.0


class FirstBreakoutFilter:
    """Filters out the first breakout attempt and waits for confirmation.

    Usage:
        filter = FirstBreakoutFilter()
        status = filter.update(price, vah, val, volume, avg_volume)
        if status.state == BreakoutState.CONFIRMED_BREAKOUT:
            # Safe to trade
    """

    def __init__(
        self,
        confirmation_bars: int = 2,
        volume_multiplier: float = 1.2,
    ):
        self._confirmation_bars = confirmation_bars
        self._volume_multiplier = volume_multiplier
        self._state = BreakoutState.NO_ATTEMPT
        self._direction = ""
        self._attempt_count = 0
        self._confirmation_count = 0
        self._failed_level = 0.0
        self._last_price_outside = 0.0

    def update(
        self,
        price: float,
        vah: float,
        val: float,
        volume: float = 0.0,
        avg_volume: float = 0.0,
    ) -> BreakoutStatus:
        """Process a new candle and update breakout state.

        Args:
            price: Candle close price
            vah: Value Area High
            val: Value Area Low
            volume: Candle volume
            avg_volume: Average volume
        """
        if vah <= 0 or val <= 0:
            return BreakoutStatus(
                state=self._state,
                direction=self._direction,
                attempt_count=self._attempt_count,
                confirmation_bars=self._confirmation_count,
                failed_at_level=self._failed_level,
            )

        is_above = price > vah
        is_below = price < val
        is_inside = val <= price <= vah

        # Volume confirmation
        volume_confirmed = True
        if avg_volume > 0 and volume > 0:
            volume_confirmed = volume >= avg_volume * self._volume_multiplier

        if self._state == BreakoutState.NO_ATTEMPT:
            if is_above:
                self._state = BreakoutState.FIRST_ATTEMPT
                self._direction = "UP"
                self._attempt_count = 1
                self._confirmation_count = 1 if volume_confirmed else 0
                self._last_price_outside = price
            elif is_below:
                self._state = BreakoutState.FIRST_ATTEMPT
                self._direction = "DOWN"
                self._attempt_count = 1
                self._confirmation_count = 1 if volume_confirmed else 0
                self._last_price_outside = price

        elif self._state == BreakoutState.FIRST_ATTEMPT:
            if is_inside:
                # First breakout failed — snapped back inside
                self._state = BreakoutState.FIRST_FAILED
                self._failed_level = vah if self._direction == "UP" else val
                self._confirmation_count = 0
            else:
                # Still outside — count confirmation bars
                if self._direction == "UP" and is_above:
                    if volume_confirmed:
                        self._confirmation_count += 1
                    self._last_price_outside = price
                elif self._direction == "DOWN" and is_below:
                    if volume_confirmed:
                        self._confirmation_count += 1
                    self._last_price_outside = price

                # Check if confirmed
                if self._confirmation_count >= self._confirmation_bars:
                    self._state = BreakoutState.CONFIRMED_BREAKOUT

        elif self._state == BreakoutState.FIRST_FAILED:
            # After failure, we switch to mean reversion mode
            # Don't allow trend entries until next session reset
            pass  # State remains FIRST_FAILED

        elif self._state == BreakoutState.CONFIRMED_BREAKOUT:
            if is_inside:
                # Price pulled back inside — re-test mode
                self._state = BreakoutState.RE_TESTING
                self._confirmation_count = 0
            else:
                # Still in breakout — continue tracking
                self._last_price_outside = price

        elif self._state == BreakoutState.RE_TESTING:
            if is_above and self._direction == "UP":
                # Re-test of VAH held — breakout resuming
                self._state = BreakoutState.CONFIRMED_BREAKOUT
                self._confirmation_count = 1
            elif is_below and self._direction == "DOWN":
                self._state = BreakoutState.CONFIRMED_BREAKOUT
                self._confirmation_count = 1
            elif is_inside:
                # Still inside — stay in re-test mode
                pass
            else:
                # Wrong direction — breakout failed
                self._state = BreakoutState.FIRST_FAILED
                self._failed_level = 0.0

        return BreakoutStatus(
            state=self._state,
            direction=self._direction,
            attempt_count=self._attempt_count,
            confirmation_bars=self._confirmation_count,
            failed_at_level=self._failed_level,
        )

    @property
    def is_confirmed(self) -> bool:
        return self._state == BreakoutState.CONFIRMED_BREAKOUT

    @property
    def is_retesting(self) -> bool:
        return self._state == BreakoutState.RE_TESTING

    @property
    def is_first_failed(self) -> bool:
        return self._state == BreakoutState.FIRST_FAILED

    @property
    def breakout_direction(self) -> str:
        return self._direction

    @property
    def failed_level(self) -> float:
        return self._failed_level

    def reset(self) -> None:
        """Reset for new session."""
        self._state = BreakoutState.NO_ATTEMPT
        self._direction = ""
        self._attempt_count = 0
        self._confirmation_count = 0
        self._failed_level = 0.0
        self._last_price_outside = 0.0
