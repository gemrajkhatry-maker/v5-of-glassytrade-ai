"""Anchored VWAP with ±1σ/±2σ bands and anti-climax (AMT §6.1).

Port of quant/amt/profile/vwap.py::SessionVWAP session-accumulation path
(shifted-variance numerics kept verbatim). Stdlib only, no v1 imports.
"""

from __future__ import annotations

import math

from quantv2.types import Bar


class AnchoredVWAP:
    """Volume-weighted anchored VWAP over typical prices with σ bands.

    Typical price defaults to (high + low + close) / 3 (v1 SessionVWAP).
    Variance is volume-weighted with a first-typical shift for numerical
    stability: σ² = Σ((TP − shift)²·V)/ΣV − (vwap − shift)².  Anti-climax
    (AMT §6.1) = close beyond ±2σ.  Not thread-safe; call reset() at anchor.
    """

    def __init__(self) -> None:
        self._cum_vol: float = 0.0
        self._cum_quote_vol: float = 0.0
        self._cum_sq_vol: float = 0.0
        self._shift: float = 0.0

    def on_bar(self, bar: Bar, typical_price: float | None = None) -> None:
        """Accumulate one completed bar into the anchored VWAP."""
        vol = float(bar.volume)
        if vol <= 0:
            return
        tp = float(typical_price) if typical_price is not None else (bar.high + bar.low + bar.close) / 3.0
        self._cum_vol += vol
        self._cum_quote_vol += tp * vol
        if self._shift == 0.0:
            self._shift = tp
        shifted = tp - self._shift
        self._cum_sq_vol += shifted * shifted * vol

    def reset(self) -> None:
        """Reset all accumulators (re-anchor at next on_bar)."""
        self._cum_vol = 0.0
        self._cum_quote_vol = 0.0
        self._cum_sq_vol = 0.0
        self._shift = 0.0

    @property
    def vwap(self) -> float:
        """Current anchored VWAP (0.0 when no volume accumulated)."""
        return self._cum_quote_vol / self._cum_vol if self._cum_vol > 0 else 0.0

    @property
    def sigma(self) -> float:
        """Volume-weighted standard deviation of typical prices about the VWAP."""
        if self._cum_vol <= 0 or self._shift == 0.0:
            return 0.0
        variance = max(0.0, self._cum_sq_vol / self._cum_vol - (self.vwap - self._shift) ** 2)
        return math.sqrt(variance)

    @property
    def sigma1_up(self) -> float:
        return self.vwap + self.sigma

    @property
    def sigma1_dn(self) -> float:
        return self.vwap - self.sigma

    @property
    def sigma2_up(self) -> float:
        return self.vwap + 2.0 * self.sigma

    @property
    def sigma2_dn(self) -> float:
        return self.vwap - 2.0 * self.sigma

    def anti_climax(self, close: float) -> bool:
        """True when close is beyond ±2σ (climax extension, AMT §6.1)."""
        if self.sigma <= 0.0:
            return False
        return close > self.sigma2_up or close < self.sigma2_dn
