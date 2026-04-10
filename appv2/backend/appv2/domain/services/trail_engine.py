"""Trail Engine — ATR trailing, VWAP trailing, CVD breakeven.

Manages dynamic stop-loss trailing for open positions.
Three trailing modes:
1. ATR Trailing — SL follows price at X×ATR distance
2. VWAP Trailing — SL follows VWAP for longs (VWAP for shorts)
3. CVD Breakeven — move SL to breakeven when CVD confirms
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrailResult:
    new_stop_loss: float  # Updated SL (0 = no change)
    moved_to_breakeven: bool  # SL moved to entry price
    trail_type: str  # "ATR" | "VWAP" | "CVD" | ""


class TrailEngine:
    """Manages trailing stop-loss for open positions."""

    def __init__(
        self,
        atr_multiplier: float = 2.0,
        vwap_offset: float = 0.0,
        cvd_breakeven_threshold: float = 2.0,
    ):
        self._atr_mult = atr_multiplier
        self._vwap_offset = vwap_offset
        self._cvd_breakeven_thresh = cvd_breakeven_threshold
        self._breakeven_moved: set[str] = set()  # trade_ids already moved to BE

    def atr_trail(
        self,
        is_long: bool,
        current_price: float,
        current_sl: float,
        atr: float,
        entry_price: float,
    ) -> TrailResult:
        """ATR-based trailing stop-loss.

        LONG: SL = max(current SL, current_price - atr × multiplier)
        SHORT: SL = min(current SL, current_price + atr × multiplier)
        """
        if atr <= 0:
            return TrailResult(0, False, "")

        if is_long:
            new_sl = current_price - (atr * self._atr_mult)
            # Only tighten, never loosen
            if new_sl > current_sl:
                # Never trail below entry (protect capital)
                new_sl = max(new_sl, entry_price)
                return TrailResult(round(new_sl, 4), False, "ATR")
        else:
            new_sl = current_price + (atr * self._atr_mult)
            if current_sl == 0 or new_sl < current_sl:
                new_sl = min(new_sl, entry_price)
                return TrailResult(round(new_sl, 4), False, "ATR")

        return TrailResult(0, False, "")

    def vwap_trail(
        self,
        is_long: bool,
        current_sl: float,
        vwap: float,
        entry_price: float,
    ) -> TrailResult:
        """VWAP-based trailing stop-loss.

        LONG: SL = VWAP - offset (only if VWAP > entry)
        SHORT: SL = VWAP + offset (only if VWAP < entry)
        """
        if vwap <= 0:
            return TrailResult(0, False, "")

        if is_long and vwap > entry_price:
            new_sl = vwap - self._vwap_offset
            if new_sl > current_sl:
                return TrailResult(round(new_sl, 4), False, "VWAP")
        elif not is_long and vwap < entry_price:
            new_sl = vwap + self._vwap_offset
            if current_sl == 0 or new_sl < current_sl:
                return TrailResult(round(new_sl, 4), False, "VWAP")

        return TrailResult(0, False, "")

    def cvd_breakeven(
        self,
        trade_id: str,
        is_long: bool,
        current_sl: float,
        entry_price: float,
        cvd_slope: float,
        profit_buffer: float = 0.0,
    ) -> TrailResult:
        """Move SL to breakeven when CVD confirms direction.

        Triggers when:
        - Trade is in profit (price moved favorably)
        - CVD slope confirms direction (> threshold for long, <-threshold for short)
        - Not already moved to breakeven
        """
        if trade_id in self._breakeven_moved:
            return TrailResult(0, False, "")

        # Check if CVD confirms
        if is_long and cvd_slope < self._cvd_breakeven_thresh:
            return TrailResult(0, False, "")
        if not is_long and cvd_slope > -self._cvd_breakeven_thresh:
            return TrailResult(0, False, "")

        # Move to breakeven (+ small profit buffer)
        if is_long:
            new_sl = entry_price + profit_buffer
            if new_sl > current_sl:
                self._breakeven_moved.add(trade_id)
                return TrailResult(round(new_sl, 4), True, "CVD")
        else:
            new_sl = entry_price - profit_buffer
            if current_sl == 0 or new_sl < current_sl:
                self._breakeven_moved.add(trade_id)
                return TrailResult(round(new_sl, 4), True, "CVD")

        return TrailResult(0, False, "")

    def update(
        self,
        trade_id: str,
        is_long: bool,
        current_price: float,
        current_sl: float,
        entry_price: float,
        atr: float = 0.0,
        vwap: float = 0.0,
        cvd_slope: float = 0.0,
        use_atr: bool = True,
        use_vwap: bool = False,
        use_cvd_be: bool = True,
    ) -> TrailResult:
        """Combined trailing update — tries all active modes.

        Priority: CVD Breakeven > VWAP Trail > ATR Trail
        """
        # 1. Try CVD breakeven first
        if use_cvd_be:
            result = self.cvd_breakeven(trade_id, is_long, current_sl, entry_price, cvd_slope)
            if result.new_stop_loss > 0:
                return result

        # 2. Try VWAP trail
        if use_vwap and vwap > 0:
            result = self.vwap_trail(is_long, current_sl, vwap, entry_price)
            if result.new_stop_loss > 0:
                return result

        # 3. Try ATR trail
        if use_atr and atr > 0:
            result = self.atr_trail(is_long, current_price, current_sl, atr, entry_price)
            if result.new_stop_loss > 0:
                return result

        return TrailResult(0, False, "")

    def reset(self, trade_id: str = "") -> None:
        """Reset breakeven tracking."""
        if trade_id:
            self._breakeven_moved.discard(trade_id)
        else:
            self._breakeven_moved.clear()
