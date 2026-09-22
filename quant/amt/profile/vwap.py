"""SessionVWAP — session VWAP accumulator with σ bands and ATR.

Extracted from AMTAnalyzer (audit: god-class decomposition, step 1).
Owns the cumulative volume, quote-volume, and shifted-variance accumulators
that track the session VWAP tick-by-tick, plus the session bar ring buffer
for ATR computation.

Call ``update()`` on each new candle; call ``reset()`` on session boundary.
All other callers read via ``vwap``, ``std``, ``bands()``.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC

logger = logging.getLogger(__name__)


class SessionVWAP:
    """Session-scoped VWAP accumulator with σ-band computation.

    Accumulates ``typical_price × volume`` per candle, computes volume-weighted
    VWAP and shifted-variance σ.  Also maintains a bounded ring buffer of
    session bars for ATR computation.

    Thread safety: NOT thread-safe — callers must serialize (AMTEngine._amt_lock).
    """

    def __init__(self, max_session_bars: int = 500) -> None:
        self._max_session_bars = max_session_bars
        # Accumulators
        self._cum_vol: float = 0.0
        self._cum_quote_vol: float = 0.0
        self._cum_sq_vol: float = 0.0  # Σ((TP - shift)² × volume)
        self._shift: float = 0.0       # Reference price for numerical stability
        self._last_time: str = ""
        # Session bar ring buffer (for ATR)
        self._session_bars: list[OHLC] = []

    # ------------------------------------------------------------------
    # Accumulation
    # ------------------------------------------------------------------

    def update(self, bar: OHLC, typical_price: float) -> float:
        """Accumulate one candle into the session VWAP.

        Deduplicates sub-candle re-feeds (same ``bar.time`` → skip accumulation
        but still append to session bars).

        Returns the current session VWAP.
        """
        is_new_candle = bar.time != self._last_time
        self._last_time = bar.time

        if is_new_candle:
            vol = float(bar.volume)
            if vol > 0:
                self._cum_vol += vol
                self._cum_quote_vol += typical_price * vol

                if self._shift == 0.0:
                    self._shift = typical_price
                shifted = typical_price - self._shift
                self._cum_sq_vol += shifted * shifted * vol

        # Session bar ring buffer (dedup on bar.time)
        if not self._session_bars or self._session_bars[-1].time != bar.time:
            self._session_bars.append(bar)
            if len(self._session_bars) > self._max_session_bars:
                self._session_bars = self._session_bars[-self._max_session_bars:]

        return self.vwap(bar_close=bar.close)

    def reset(self) -> None:
        """Reset all accumulators on session boundary."""
        self._cum_vol = 0.0
        self._cum_quote_vol = 0.0
        self._cum_sq_vol = 0.0
        self._shift = 0.0
        self._session_bars = []

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def vwap_value(self) -> float:
        """Current session VWAP (0.0 when no volume accumulated)."""
        return self._cum_quote_vol / self._cum_vol if self._cum_vol > 0 else 0.0

    def vwap(self, bar_close: float = 0.0) -> float:
        """Current session VWAP, falling back to bar_close when no volume."""
        v = self.vwap_value
        return v if v > 0 else bar_close

    @property
    def std(self) -> float:
        """Volume-weighted session VWAP standard deviation."""
        if self._cum_vol <= 0 or self._shift == 0.0:
            return 0.0
        variance = max(
            0.0,
            self._cum_sq_vol / self._cum_vol - (self.vwap_value - self._shift) ** 2,
        )
        return math.sqrt(variance)

    @property
    def session_bars(self) -> list[OHLC]:
        """Session bar ring buffer (for ATR and other consumers)."""
        return self._session_bars

    # ------------------------------------------------------------------
    # Static helpers (pure functions, no state)
    # ------------------------------------------------------------------

    @staticmethod
    def recent_stats(recent_data: list[OHLC]) -> tuple[float, float]:
        """Volume-weighted VWAP + std over an explicit candle window.

        Same shifted-variance math as the session path but over the given
        window.  Used so VWAP bands and deviation sigma are computed on the
        SAME window as the VA clamp (RECENT_VA_LOOKBACK).
        """
        tot_vol = 0.0
        tot_quote = 0.0
        tot_sq = 0.0
        shift = 0.0
        for d in recent_data:
            tp = (float(d.high) + float(d.low) + float(d.close)) / 3.0
            v = float(d.volume)
            if v <= 0:
                continue
            if shift == 0.0:
                shift = tp
            tot_vol += v
            tot_quote += tp * v
            s = tp - shift
            tot_sq += s * s * v
        if tot_vol <= 0:
            return 0.0, 0.0
        vwap = tot_quote / tot_vol
        variance = max(0.0, tot_sq / tot_vol - (vwap - shift) ** 2)
        # Raw statistical σ — never floor/cap here. Publishing a clamped band
        # as vwap_std lied to anti-climax / journals (audit §1.7).
        vwap_std = math.sqrt(variance)
        return vwap, vwap_std

    @staticmethod
    def compute_atr(bars: list[OHLC], period: int = 14) -> float:
        """Average True Range over the last ``period`` bars."""
        if len(bars) < 2:
            return 0.0
        trs: list[float] = []
        for i in range(1, len(bars)):
            high = float(bars[i].high)
            low = float(bars[i].low)
            prev_close = float(bars[i - 1].close)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        if not trs:
            return 0.0
        window = trs[-period:]
        return sum(window) / len(window)

    # ------------------------------------------------------------------
    # VWAP σ bands
    # ------------------------------------------------------------------

    def bands(
        self,
        session_vwap: float,
        current: OHLC,
        recent_data: list[OHLC] | None = None,
    ) -> tuple[float, float, float, float, float, float | None]:
        """Compute VWAP standard deviation bands (±1σ, ±2σ).

        When ``recent_data`` is provided the VWAP and std are recomputed
        volume-weighted over that window (the same basis as the VA clamp).
        Otherwise the whole-session accumulators are used.
        """
        if recent_data:
            session_vwap, vwap_std = SessionVWAP.recent_stats(recent_data)
        else:
            vwap_std = self.std

        vwap_upper_1 = session_vwap + vwap_std
        vwap_lower_1 = session_vwap - vwap_std
        vwap_upper_2 = session_vwap + 2 * vwap_std
        vwap_lower_2 = session_vwap - 2 * vwap_std

        live_price = float(current.close)
        vwap_deviation_sigmas: float | None = (
            (live_price - session_vwap) / vwap_std if vwap_std > 0 else None
        )

        # Sanity: clamp extreme deviations
        if vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) > 4.0:
            logger.debug(
                "VWAP deviation clamped: %.2fσ → ±4.0σ", vwap_deviation_sigmas,
            )
            vwap_deviation_sigmas = 4.0 if vwap_deviation_sigmas > 0 else -4.0

        return (
            vwap_upper_1, vwap_lower_1,
            vwap_upper_2, vwap_lower_2,
            vwap_std, vwap_deviation_sigmas,
        )
