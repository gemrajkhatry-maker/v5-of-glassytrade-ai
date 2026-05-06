"""IB breakout scalp engines for continuation and failed-breakout plays."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.domain.services.initial_balance_engine import IBState, IBLocation

logger = logging.getLogger(__name__)


class IBScalpType(str, Enum):
    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    NONE = "NONE"


@dataclass(frozen=True)
class IBScalpSignal:
    scalp_type: IBScalpType
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    setup_valid: bool
    rejection_reason: str


class IBBreakoutScalpEngine:
    """Evaluate IB breakout continuation and failed breakout setups."""

    def __init__(
        self,
        min_rr_ratio: float = 1.5,
        retest_max_bars: int = 3,
        volume_multiplier: float = 1.5,
    ) -> None:
        self._min_rr = float(min_rr_ratio)
        self._retest_max_bars = int(retest_max_bars)
        self._vol_mult = float(volume_multiplier)
        self._breakout_direction: str = ""
        self._breakout_bar_index: int = 0
        self._breakout_price: float = 0.0
        self._breakout_detected = False

    def reset(self) -> None:
        self._breakout_direction = ""
        self._breakout_bar_index = 0
        self._breakout_price = 0.0
        self._breakout_detected = False

    def _ib_location(self, ib_state: IBState, price: float) -> IBLocation:
        if not ib_state.is_complete:
            return IBLocation.BUILDING
        if price > ib_state.ib_high:
            return IBLocation.ABOVE
        if price < ib_state.ib_low:
            return IBLocation.BELOW
        return IBLocation.INSIDE

    def evaluate_setup_a(
        self,
        ib_state: IBState,
        current_price: float,
        current_high: float,
        current_low: float,
        current_volume: float,
        avg_volume: float,
        cvd_slope_1m: float,
        bar_index: int,
        tick_size: float,
    ) -> IBScalpSignal:
        if not ib_state.is_complete:
            return IBScalpSignal(
                IBScalpType.NONE, "", 0.0, 0.0, 0.0, 0.0, False, "IB not complete"
            )
        if ib_state.ib_width <= 0:
            return IBScalpSignal(
                IBScalpType.NONE, "", 0.0, 0.0, 0.0, 0.0, False, "IB width is zero"
            )

        ib_high = ib_state.ib_high
        ib_low = ib_state.ib_low
        ib_width = ib_state.ib_width

        # LONG breakout candidate
        if current_high > ib_high:
            if not self._breakout_detected:
                self._breakout_detected = True
                self._breakout_direction = "LONG"
                self._breakout_bar_index = int(bar_index)
                self._breakout_price = ib_high
            if current_volume < avg_volume * self._vol_mult:
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "LONG",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    False,
                    "Volume not confirmed",
                )
            if cvd_slope_1m <= 0:
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "LONG",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    False,
                    "1-min CVD not positive",
                )
            bars_since = bar_index - self._breakout_bar_index
            if bars_since > self._retest_max_bars:
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "LONG",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    False,
                    "Retest window expired",
                )
            if abs(current_price - ib_high) <= tick_size * 3:
                entry = ib_high
                stop_loss = ib_high - tick_size
                take_profit = ib_high + ib_width
                rr = (take_profit - entry) / max(entry - stop_loss, 1e-9)
                if rr < self._min_rr:
                    return IBScalpSignal(
                        IBScalpType.BREAKOUT_CONTINUATION,
                        "LONG",
                        entry,
                        stop_loss,
                        take_profit,
                        round(rr, 2),
                        False,
                        f"R:R {rr:.1f} < {self._min_rr}",
                    )
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "LONG",
                    entry,
                    stop_loss,
                    take_profit,
                    round(rr, 2),
                    True,
                    "",
                )

        # SHORT breakout candidate
        if current_low < ib_low:
            if not self._breakout_detected:
                self._breakout_detected = True
                self._breakout_direction = "SHORT"
                self._breakout_bar_index = int(bar_index)
                self._breakout_price = ib_low
            if current_volume < avg_volume * self._vol_mult:
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "SHORT",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    False,
                    "Volume not confirmed",
                )
            if cvd_slope_1m >= 0:
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "SHORT",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    False,
                    "1-min CVD not negative",
                )
            bars_since = bar_index - self._breakout_bar_index
            if bars_since > self._retest_max_bars:
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "SHORT",
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    False,
                    "Retest window expired",
                )
            if abs(current_price - ib_low) <= tick_size * 3:
                entry = ib_low
                stop_loss = ib_low + tick_size
                take_profit = ib_low - ib_width
                rr = (entry - take_profit) / max(stop_loss - entry, 1e-9)
                if rr < self._min_rr:
                    return IBScalpSignal(
                        IBScalpType.BREAKOUT_CONTINUATION,
                        "SHORT",
                        entry,
                        stop_loss,
                        take_profit,
                        round(rr, 2),
                        False,
                        f"R:R {rr:.1f} < {self._min_rr}",
                    )
                return IBScalpSignal(
                    IBScalpType.BREAKOUT_CONTINUATION,
                    "SHORT",
                    entry,
                    stop_loss,
                    take_profit,
                    round(rr, 2),
                    True,
                    "",
                )

        return IBScalpSignal(
            IBScalpType.NONE, "", 0.0, 0.0, 0.0, 0.0, False, "No breakout detected"
        )

    def evaluate_setup_b(
        self,
        ib_state: IBState,
        current_price: float,
        current_close: float,
        current_high: float,
        current_low: float,
        cvd_slope_1m: float,
        opposing_aggression: bool,
        tick_size: float,
    ) -> IBScalpSignal:
        if not ib_state.is_complete:
            return IBScalpSignal(
                IBScalpType.NONE, "", 0.0, 0.0, 0.0, 0.0, False, "IB not complete"
            )
        if ib_state.ib_width <= 0:
            return IBScalpSignal(
                IBScalpType.NONE, "", 0.0, 0.0, 0.0, 0.0, False, "IB width is zero"
            )
        if not self._breakout_detected:
            return IBScalpSignal(
                IBScalpType.NONE, "", 0.0, 0.0, 0.0, 0.0, False, "No prior breakout detected"
            )

        current_location = self._ib_location(ib_state, current_close)
        if self._breakout_direction == "LONG":
            failed = (
                current_location in {IBLocation.BUILDING, IBLocation.INSIDE}
                and current_price >= ib_state.ib_low
                and current_close <= ib_state.ib_high
            )
            if failed and opposing_aggression and cvd_slope_1m < 0:
                entry = ib_state.ib_mid
                stop_loss = self._breakout_price + 2 * tick_size
                take_profit = ib_state.ib_low
                rr = (entry - take_profit) / max(stop_loss - entry, 1e-9)
                if rr < self._min_rr:
                    return IBScalpSignal(
                        IBScalpType.FAILED_BREAKOUT,
                        "LONG",
                        entry,
                        stop_loss,
                        take_profit,
                        round(rr, 2),
                        False,
                        f"R:R {rr:.1f} < {self._min_rr}",
                    )
                return IBScalpSignal(
                    IBScalpType.FAILED_BREAKOUT,
                    "LONG",
                    entry,
                    stop_loss,
                    take_profit,
                    round(rr, 2),
                    True,
                    "",
                )

        elif self._breakout_direction == "SHORT":
            failed = (
                current_location in {IBLocation.BUILDING, IBLocation.INSIDE}
                and current_price <= ib_state.ib_high
                and current_close >= ib_state.ib_low
            )
            if failed and opposing_aggression and cvd_slope_1m > 0:
                entry = ib_state.ib_mid
                stop_loss = self._breakout_price - 2 * tick_size
                take_profit = ib_state.ib_high
                rr = (take_profit - entry) / max(entry - stop_loss, 1e-9)
                if rr < self._min_rr:
                    return IBScalpSignal(
                        IBScalpType.FAILED_BREAKOUT,
                        "SHORT",
                        entry,
                        stop_loss,
                        take_profit,
                        round(rr, 2),
                        False,
                        f"R:R {rr:.1f} < {self._min_rr}",
                    )
                return IBScalpSignal(
                    IBScalpType.FAILED_BREAKOUT,
                    "SHORT",
                    entry,
                    stop_loss,
                    take_profit,
                    round(rr, 2),
                    True,
                    "",
                )

        return IBScalpSignal(
            IBScalpType.NONE,
            self._breakout_direction,
            0.0,
            0.0,
            0.0,
            0.0,
            False,
            "No failed breakout condition",
        )

