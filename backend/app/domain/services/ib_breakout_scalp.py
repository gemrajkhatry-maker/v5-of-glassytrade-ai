"""IB Breakout Scalp — Setup A (Continuation) + Setup B (Failed Breakout).

Fabio's daily setup. Uses the IBEngine from Phase 2 to detect IB completion,
then evaluates breakout/failed-breakout conditions for scalp entries.

Setup A — IB Breakout Continuation:
  Price closes above IB_HIGH with volume confirmation.
  Wait for retest of IB_HIGH from above (pullback entry).
  SL 1 tick below IB_HIGH. Target: IB_HIGH + 1× IB_WIDTH.

Setup B — IB Failed Breakout (Mean Reversion):
  Price breaks above IB_HIGH then closes back inside within 1-2 bars.
  Opposing aggression at breakout high confirms failure.
  Entry at IB_MID breach. SL above failed breakout high.
  Target: IB_LOW (full mean reversion).
"""

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
    """IB Breakout scalp signal."""

    scalp_type: IBScalpType
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    setup_valid: bool
    rejection_reason: str


class IBBreakoutScalpEngine:
    """Evaluates IB breakout and failed breakout setups.

    Called after IB completion. Monitors price action for:
    1. Breakout with retest (Setup A)
    2. Failed breakout with reversal (Setup B)
    """

    def __init__(
        self,
        min_rr_ratio: float = 1.5,
        retest_max_bars: int = 3,
        volume_multiplier: float = 1.5,
    ) -> None:
        self._min_rr = min_rr_ratio
        self._retest_max_bars = retest_max_bars
        self._vol_mult = volume_multiplier
        self._breakout_bar_index: int = 0
        self._breakout_direction: str = ""
        self._breakout_detected: bool = False

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
        """Evaluate IB Breakout Continuation setup.

        Pre-conditions:
          IB complete
          5-min bar closes ABOVE IB_HIGH (for LONG)
          Volume > 1.5× session avg
          Retest within 3 bars

        Entry: Market order at IB_HIGH retest
        SL: 1 tick below IB_HIGH
        Target: IB_HIGH + 1× IB_WIDTH
        """
        if not ib_state.is_complete:
            return IBScalpSignal(
                scalp_type=IBScalpType.NONE,
                direction="",
                entry_price=0,
                stop_loss=0,
                take_profit=0,
                rr_ratio=0,
                setup_valid=False,
                rejection_reason="IB not complete",
            )

        ib_high = ib_state.ib_high
        ib_low = ib_state.ib_low
        ib_width = ib_state.ib_width

        if ib_width <= 0:
            return IBScalpSignal(
                scalp_type=IBScalpType.NONE,
                direction="",
                entry_price=0,
                stop_loss=0,
                take_profit=0,
                rr_ratio=0,
                setup_valid=False,
                rejection_reason="IB width is zero",
            )

        # Check for LONG breakout
        if current_high > ib_high:
            if not self._breakout_detected:
                self._breakout_detected = True
                self._breakout_direction = "LONG"
                self._breakout_bar_index = bar_index

            # Volume confirmation
            if current_volume < avg_volume * self._vol_mult:
                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="LONG",
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    rr_ratio=0,
                    setup_valid=False,
                    rejection_reason="Volume not confirmed",
                )

            # CVD confirmation
            if cvd_slope_1m <= 0:
                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="LONG",
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    rr_ratio=0,
                    setup_valid=False,
                    rejection_reason="1-min CVD not positive",
                )

            # Retest check: price came back to IB_HIGH
            bars_since_breakout = bar_index - self._breakout_bar_index
            if bars_since_breakout > self._retest_max_bars:
                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="LONG",
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    rr_ratio=0,
                    setup_valid=False,
                    rejection_reason="Retest window expired",
                )

            # Retest: current price near IB_HIGH
            if abs(current_price - ib_high) <= tick_size * 3:
                entry = ib_high
                sl = ib_high - tick_size  # 1 tick below IB_HIGH
                tp = ib_high + ib_width  # measured move
                risk = entry - sl
                reward = tp - entry
                rr = reward / risk if risk > 0 else 0

                if rr < self._min_rr:
                    return IBScalpSignal(
                        scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                        direction="LONG",
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        rr_ratio=rr,
                        setup_valid=False,
                        rejection_reason=f"R:R {rr:.1f} < {self._min_rr}",
                    )

                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="LONG",
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    rr_ratio=rr,
                    setup_valid=True,
                    rejection_reason="",
                )

        # Check for SHORT breakout (mirror)
        if current_low < ib_low:
            if not self._breakout_detected:
                self._breakout_detected = True
                self._breakout_direction = "SHORT"
                self._breakout_bar_index = bar_index

            if current_volume < avg_volume * self._vol_mult:
                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="SHORT",
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    rr_ratio=0,
                    setup_valid=False,
                    rejection_reason="Volume not confirmed",
                )

            if cvd_slope_1m >= 0:
                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="SHORT",
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    rr_ratio=0,
                    setup_valid=False,
                    rejection_reason="1-min CVD not negative",
                )

            bars_since_breakout = bar_index - self._breakout_bar_index
            if bars_since_breakout > self._retest_max_bars:
                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="SHORT",
                    entry_price=0,
                    stop_loss=0,
                    take_profit=0,
                    rr_ratio=0,
                    setup_valid=False,
                    rejection_reason="Retest window expired",
                )

            if abs(current_price - ib_low) <= tick_size * 3:
                entry = ib_low
                sl = ib_low + tick_size
                tp = ib_low - ib_width
                risk = sl - entry
                reward = entry - tp
                rr = reward / risk if risk > 0 else 0

                if rr < self._min_rr:
                    return IBScalpSignal(
                        scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                        direction="SHORT",
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        rr_ratio=rr,
                        setup_valid=False,
                        rejection_reason=f"R:R {rr:.1f} < {self._min_rr}",
                    )

                return IBScalpSignal(
                    scalp_type=IBScalpType.BREAKOUT_CONTINUATION,
                    direction="SHORT",
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    rr_ratio=rr,
                    setup_valid=True,
                    rejection_reason="",
                )

        return IBScalpSignal(
            scalp_type=IBScalpType.NONE,
            direction="",
            entry_price=0,
            stop_loss=0,
            take_profit=0,
            rr_ratio=0,
            setup_valid=False,
            rejection_reason="No breakout detected",
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
        """Evaluate IB Failed Breakout (Mean Reversion) setup.

        Pre-conditions:
          IB complete
          Price previously broke above IB_HIGH (breakout)
          Within 1-2 bars: price closes BACK INSIDE IB (failure)
          Opposing aggression at breakout high
          1-min CVD flips at the high

        Entry: Market order at IB_MID breach
        SL: Above failed breakout high + 2 ticks
        Target: IB_LOW (full mean reversion)
        """
        if not ib_state.is_complete:
            return IBScalpSignal(
                scalp_type=IBScalpType.NONE,
                direction="",
                entry_price=0,
                stop_loss=0,
                take_profit=0,
                rr_ratio=0,
                setup_valid=False,
                rejection_reason="IB not complete",
            )

        ib_high = ib_state.ib_high
        ib_low = ib_state.ib_low
        ib_mid = ib_state.ib_mid
        ib_width = ib_state.ib_width

        # Failed breakout: price was above IB_HIGH, now back inside
        if self._breakout_detected and self._breakout_direction == "LONG":
            if current_close < ib_high and current_close > ib_low:
                # Price reclaimed IB — failed breakout
                if not opposing_aggression:
                    return IBScalpSignal(
                        scalp_type=IBScalpType.FAILED_BREAKOUT,
                        direction="SHORT",
                        entry_price=0,
                        stop_loss=0,
                        take_profit=0,
                        rr_ratio=0,
                        setup_valid=False,
                        rejection_reason="No opposing aggression at breakout high",
                    )

                if cvd_slope_1m >= 0:
                    return IBScalpSignal(
                        scalp_type=IBScalpType.FAILED_BREAKOUT,
                        direction="SHORT",
                        entry_price=0,
                        stop_loss=0,
                        take_profit=0,
                        rr_ratio=0,
                        setup_valid=False,
                        rejection_reason="1-min CVD not negative at failure",
                    )

                # Entry at IB_MID breach
                if current_close <= ib_mid:
                    entry = ib_mid
                    sl = current_high + 2 * tick_size  # above failed breakout high
                    tp = ib_low  # full mean reversion
                    risk = sl - entry
                    reward = entry - tp
                    rr = reward / risk if risk > 0 else 0

                    if rr < self._min_rr:
                        return IBScalpSignal(
                            scalp_type=IBScalpType.FAILED_BREAKOUT,
                            direction="SHORT",
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            rr_ratio=rr,
                            setup_valid=False,
                            rejection_reason=f"R:R {rr:.1f} < {self._min_rr}",
                        )

                    return IBScalpSignal(
                        scalp_type=IBScalpType.FAILED_BREAKOUT,
                        direction="SHORT",
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        rr_ratio=rr,
                        setup_valid=True,
                        rejection_reason="",
                    )

        # Failed SHORT breakout (mirror)
        if self._breakout_detected and self._breakout_direction == "SHORT":
            if current_close > ib_low and current_close < ib_high:
                if not opposing_aggression:
                    return IBScalpSignal(
                        scalp_type=IBScalpType.FAILED_BREAKOUT,
                        direction="LONG",
                        entry_price=0,
                        stop_loss=0,
                        take_profit=0,
                        rr_ratio=0,
                        setup_valid=False,
                        rejection_reason="No opposing aggression at breakout low",
                    )

                if cvd_slope_1m <= 0:
                    return IBScalpSignal(
                        scalp_type=IBScalpType.FAILED_BREAKOUT,
                        direction="LONG",
                        entry_price=0,
                        stop_loss=0,
                        take_profit=0,
                        rr_ratio=0,
                        setup_valid=False,
                        rejection_reason="1-min CVD not positive at failure",
                    )

                if current_close >= ib_mid:
                    entry = ib_mid
                    sl = current_low - 2 * tick_size
                    tp = ib_high
                    risk = entry - sl
                    reward = tp - entry
                    rr = reward / risk if risk > 0 else 0

                    if rr < self._min_rr:
                        return IBScalpSignal(
                            scalp_type=IBScalpType.FAILED_BREAKOUT,
                            direction="LONG",
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            rr_ratio=rr,
                            setup_valid=False,
                            rejection_reason=f"R:R {rr:.1f} < {self._min_rr}",
                        )

                    return IBScalpSignal(
                        scalp_type=IBScalpType.FAILED_BREAKOUT,
                        direction="LONG",
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        rr_ratio=rr,
                        setup_valid=True,
                        rejection_reason="",
                    )

        return IBScalpSignal(
            scalp_type=IBScalpType.NONE,
            direction="",
            entry_price=0,
            stop_loss=0,
            take_profit=0,
            rr_ratio=0,
            setup_valid=False,
            rejection_reason="No failed breakout detected",
        )

    def reset(self) -> None:
        """Reset for new session."""
        self._breakout_bar_index = 0
        self._breakout_direction = ""
        self._breakout_detected = False
