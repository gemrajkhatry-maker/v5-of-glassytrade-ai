"""Valentini Triple-A state machine: absorption -> accumulation -> aggression.

AGGRESSION TRIGGER (spec §8): A full 1-min candle CLOSES strictly beyond the
high of the absorption cluster (LONG) or below the low of the cluster (SHORT).
This is the canonical Fabio entry trigger — the "sniper entry" that waits for
the market to prove it wants to go.

DATA CEILING FALLBACK: When cluster_high/cluster_low are not available from
the Absorption object (legacy path or zero values), this machine falls back to
the VWAP ±1σ proxy used historically. The absorption.cluster_high/low fields
are now populated by AbsorptionDetector (quant/absorption.py) so the fallback
should only trigger in edge cases.

The richer 7-factor aggression score (footprint/CVD/big-trade/OFI) computed
by the AMT analyzer is advisory only — it feeds the UI DTO, not the gate.
"""

from __future__ import annotations

from quant.absorption import Absorption
from quant.bars import Bar
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState


class TripleAStateMachine:
    def __init__(self, near_poc_step_mult: float = 2.0) -> None:
        self._near_poc_step_mult = near_poc_step_mult
        self._phase = "WAITING"
        self._last_signal: str | None = None
        self._absorption_side: str | None = None
        self._absorption_price: float = 0.0
        self._absorption_cluster_high: float = 0.0  # From Absorption.cluster_high
        self._absorption_cluster_low: float = 0.0   # From Absorption.cluster_low
        self._absorb_bars: int = 0

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def last_signal(self) -> str | None:
        return self._last_signal

    def update(
        self,
        bar: Bar,
        vp: VolumeProfile,
        vwap: VWAPState,
        absorption: Absorption | None,
    ) -> str:
        """Process one bar, return the phase after it: WAITING | ABSORBING | ACCUMULATING | AGGRESSION."""
        if self._phase == "AGGRESSION":
            self._phase = "WAITING"
            self._last_signal = None

        # Only a FRESH detection (bar_age == 0) re-arms the machine. A stale
        # carry-over (bar_age > 0) is just context — it must count as an
        # elapsed bar so accumulation can progress to AGGRESSION.
        if absorption is not None and absorption.bar_age == 0:
            self._rearm(absorption)
            return self._phase

        if self._phase == "WAITING":
            return "WAITING"

        if self._phase == "ABSORBING":
            if vp.step <= 0 or vp.poc <= 0:
                return "ABSORBING"
            self._absorb_bars += 1
            if self._absorb_bars < 2:
                return "ABSORBING"
            near_poc = abs(bar.close - vp.poc) <= self._near_poc_step_mult * vp.step
            if not near_poc:
                return "ABSORBING"
            self._phase = "ACCUMULATING"

        return self._resolve_aggression(bar, vwap, absorption)

    def _rearm(self, absorption: Absorption) -> None:
        if self._phase != "WAITING" and absorption.side == self._absorption_side:
            self._absorption_price = absorption.price
            self._absorption_cluster_high = float(absorption.cluster_high or 0.0)
            self._absorption_cluster_low = float(absorption.cluster_low or 0.0)
            self._absorb_bars = 0
            return
        self._phase = "ABSORBING"
        self._absorption_side = absorption.side
        self._absorption_price = absorption.price
        self._absorption_cluster_high = float(absorption.cluster_high or 0.0)
        self._absorption_cluster_low = float(absorption.cluster_low or 0.0)
        self._absorb_bars = 0

    def _resolve_aggression(self, bar: Bar, vwap: VWAPState, absorption: Absorption | None = None) -> str:
        """Check if price breaks out beyond VWAP band AND closes beyond the absorption cluster.

        Spec §8:
          LONG:  bar.close > vwap.upper_1 AND bar.close > cluster_high
          SHORT: bar.close < vwap.lower_1 AND bar.close < cluster_low

        If accumulation exceeds 15 bars without breakout, the setup is stale
        and resets to WAITING per Fabio anti-stale accumulation rule.
        """
        if absorption is not None and absorption.bar_age > 15:
            self._phase = "WAITING"
            self._last_signal = None
            return "WAITING"

        cluster_high = self._absorption_cluster_high
        cluster_low = self._absorption_cluster_low

        if self._absorption_side == "BUY" and bar.close > vwap.upper_1:
            if cluster_high <= 0 or bar.close > cluster_high:
                self._phase = "AGGRESSION"
                self._last_signal = "LONG"
            else:
                self._phase = "ACCUMULATING"

        elif self._absorption_side == "SELL" and bar.close < vwap.lower_1:
            if cluster_low <= 0 or bar.close < cluster_low:
                self._phase = "AGGRESSION"
                self._last_signal = "SHORT"
            else:
                self._phase = "ACCUMULATING"

        else:
            self._phase = "ACCUMULATING"

        return self._phase
