"""Value Area Reversion Signals (VARS) Detector.

Faithful implementation of LuxAlgo's VARS Pine Script (MPL-2.0).
Detects mean-reversion reclaim signals when price breaks out of the Value Area,
experiences volume exhaustion, and violently re-enters the Value Area via an
engulfing candle with volume expansion.

Supports:
- CVA (Current Developing Session Value Area) reclaims
- PVA (Previous Completed Session Value Area) reclaims
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC


@dataclass(frozen=True)
class VARSResult:
    """Immutable result of Value Area Reversion Signals analysis."""

    bullish_reclaim_cva: bool = False
    bearish_reclaim_cva: bool = False
    bullish_reclaim_pva: bool = False
    bearish_reclaim_pva: bool = False

    # Convenience aggregate flags
    bullish_reclaim: bool = False
    bearish_reclaim: bool = False
    signal_source: str = ""  # "CVA", "PVA", "BOTH", or ""

    # Breakout context
    cva_bearish_breakout_bars: int = 0
    cva_bullish_breakout_bars: int = 0
    pva_bearish_breakout_bars: int = 0
    pva_bullish_breakout_bars: int = 0


@dataclass
class _BreakoutState:
    bearish_active: bool = False
    bullish_active: bool = False
    bearish_slowing: bool = False
    bullish_slowing: bool = False
    last_bearish_vol: float | None = None
    last_bullish_vol: float | None = None
    bearish_bars: int = 0
    bullish_bars: int = 0

    def reset(self) -> None:
        self.bearish_active = False
        self.bullish_active = False
        self.bearish_slowing = False
        self.bullish_slowing = False
        self.last_bearish_vol = None
        self.last_bullish_vol = None
        self.bearish_bars = 0
        self.bullish_bars = 0


class VARSDetector:
    """Stateful detector for LuxAlgo Value Area Reversion Signals (VARS)."""

    def __init__(
        self,
        max_reversion_bars: int = 10,
        show_current_day: bool = True,
        show_previous_day: bool = True,
    ) -> None:
        self.max_reversion_bars = max_reversion_bars
        self.show_current_day = show_current_day
        self.show_previous_day = show_previous_day

        self._cva_state = _BreakoutState()
        self._pva_state = _BreakoutState()
        self._prev_candle: OHLC | None = None

    def reset(self) -> None:
        """Reset all state upon new session/day anchor."""
        self._cva_state.reset()
        self._pva_state.reset()
        self._prev_candle = None

    def update(
        self,
        candle: OHLC,
        vah: float,
        val: float,
        poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        prior_poc: float = 0.0,
    ) -> VARSResult:
        """Process a newly closed bar and evaluate VARS signals.

        Args:
            candle: The current completed bar (OHLCV).
            vah: Current Developing Value Area High.
            val: Current Developing Value Area Low.
            poc: Current Developing Point of Control.
            prior_vah: Previous Completed Session Value Area High.
            prior_val: Previous Completed Session Value Area Low.
            prior_poc: Previous Completed Session Point of Control.
        """
        # Up/down volume calculation
        vol = float(candle.volume) if candle.volume is not None else 0.0
        up_vol = vol if candle.close >= candle.open else 0.0
        down_vol = vol if candle.close < candle.open else 0.0

        # Engulfing candlestick detection
        bullish_engulfing = False
        bearish_engulfing = False
        if self._prev_candle is not None:
            prev = self._prev_candle
            bullish_engulfing = (
                candle.close > candle.open
                and prev.close < prev.open
                and candle.open <= prev.close
                and candle.close >= prev.open
            )
            bearish_engulfing = (
                candle.close < candle.open
                and prev.close > prev.open
                and candle.open >= prev.close
                and candle.close <= prev.open
            )

        # 1. Evaluate Current Value Area (CVA)
        bullish_cva = False
        bearish_cva = False
        if self.show_current_day and vah > 0 and val > 0 and vah > val:
            bullish_cva, bearish_cva = self._evaluate_va(
                candle=candle,
                vah=vah,
                val=val,
                up_vol=up_vol,
                down_vol=down_vol,
                bullish_engulfing=bullish_engulfing,
                bearish_engulfing=bearish_engulfing,
                state=self._cva_state,
            )

        # 2. Evaluate Previous Day Value Area (PVA)
        bullish_pva = False
        bearish_pva = False
        if self.show_previous_day and prior_vah > 0 and prior_val > 0 and prior_vah > prior_val:
            bullish_pva, bearish_pva = self._evaluate_va(
                candle=candle,
                vah=prior_vah,
                val=prior_val,
                up_vol=up_vol,
                down_vol=down_vol,
                bullish_engulfing=bullish_engulfing,
                bearish_engulfing=bearish_engulfing,
                state=self._pva_state,
            )

        self._prev_candle = candle

        # Aggregate convenience flags
        bullish = bullish_cva or bullish_pva
        bearish = bearish_cva or bearish_pva
        source = ""
        if (bullish_cva or bearish_cva) and (bullish_pva or bearish_pva):
            source = "BOTH"
        elif bullish_cva or bearish_cva:
            source = "CVA"
        elif bullish_pva or bearish_pva:
            source = "PVA"

        return VARSResult(
            bullish_reclaim_cva=bullish_cva,
            bearish_reclaim_cva=bearish_cva,
            bullish_reclaim_pva=bullish_pva,
            bearish_reclaim_pva=bearish_pva,
            bullish_reclaim=bullish,
            bearish_reclaim=bearish,
            signal_source=source,
            cva_bearish_breakout_bars=self._cva_state.bearish_bars,
            cva_bullish_breakout_bars=self._cva_state.bullish_bars,
            pva_bearish_breakout_bars=self._pva_state.bearish_bars,
            pva_bullish_breakout_bars=self._pva_state.bullish_bars,
        )

    def _evaluate_va(
        self,
        candle: OHLC,
        vah: float,
        val: float,
        up_vol: float,
        down_vol: float,
        bullish_engulfing: bool,
        bearish_engulfing: bool,
        state: _BreakoutState,
    ) -> tuple[bool, bool]:
        """State machine for a single Value Area boundary set."""
        bullish_signal = False
        bearish_signal = False

        close = float(candle.close)

        if close < val:
            # Bearish breakout active below VAL
            state.bullish_active = False
            state.bullish_bars = 0
            state.bullish_slowing = False
            state.last_bullish_vol = None

            if not state.bearish_active:
                state.bearish_slowing = False
                state.last_bearish_vol = None
                state.bearish_bars = 1
            else:
                state.bearish_bars += 1

            state.bearish_active = True

            if down_vol > 0:
                if state.last_bearish_vol is not None and down_vol < state.last_bearish_vol:
                    state.bearish_slowing = True
                state.last_bearish_vol = down_vol

        elif close > vah:
            # Bullish breakout active above VAH
            state.bearish_active = False
            state.bearish_bars = 0
            state.bearish_slowing = False
            state.last_bearish_vol = None

            if not state.bullish_active:
                state.bullish_slowing = False
                state.last_bullish_vol = None
                state.bullish_bars = 1
            else:
                state.bullish_bars += 1

            state.bullish_active = True

            if up_vol > 0:
                if state.last_bullish_vol is not None and up_vol < state.last_bullish_vol:
                    state.bullish_slowing = True
                state.last_bullish_vol = up_vol

        else:
            # Inside Value Area [VAL, VAH] -> evaluate Reclaim Signals
            last_bear_vol = state.last_bearish_vol or 0.0
            last_bull_vol = state.last_bullish_vol or 0.0

            bullish_signal = (
                bullish_engulfing
                and state.bearish_active
                and state.bearish_bars <= self.max_reversion_bars
                and state.bearish_slowing
                and up_vol > down_vol
                and up_vol > last_bear_vol
            )

            bearish_signal = (
                bearish_engulfing
                and state.bullish_active
                and state.bullish_bars <= self.max_reversion_bars
                and state.bullish_slowing
                and down_vol > up_vol
                and down_vol > last_bull_vol
            )

            # Reset breakout state once price re-enters Value Area
            state.reset()

        return bullish_signal, bearish_signal
