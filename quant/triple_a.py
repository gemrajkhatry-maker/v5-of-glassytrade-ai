"""Valentini Triple-A state machine: absorption -> accumulation -> aggression."""

from __future__ import annotations

from quant.absorption import Absorption
from quant.bars import Bar
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState


class TripleAStateMachine:
    def __init__(self) -> None:
        self._phase = "WAITING"
        self._last_signal: str | None = None
        self._absorption_side: str | None = None
        self._absorption_price: float = 0.0
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

        if absorption is not None:
            self._rearm(absorption)
            return self._phase

        if self._phase == "WAITING":
            return "WAITING"

        if self._phase == "ABSORBING":
            if vp.poc == 0 and vp.step <= 0:
                return "ABSORBING"
            self._absorb_bars += 1
            if self._absorb_bars < 2:
                return "ABSORBING"
            self._phase = "ACCUMULATING"

        return self._resolve_aggression(bar, vwap)

    def _rearm(self, absorption: Absorption) -> None:
        if absorption.side == self._absorption_side:
            self._absorption_price = absorption.price
            self._absorb_bars = 0
            return
        self._phase = "ABSORBING"
        self._absorption_side = absorption.side
        self._absorption_price = absorption.price
        self._absorb_bars = 0

    def _resolve_aggression(self, bar: Bar, vwap: VWAPState) -> str:
        if self._absorption_side == "BUY" and bar.close > vwap.upper_1:
            self._phase = "AGGRESSION"
            self._last_signal = "LONG"
        elif self._absorption_side == "SELL" and bar.close < vwap.lower_1:
            self._phase = "AGGRESSION"
            self._last_signal = "SHORT"
        else:
            self._phase = "ACCUMULATING"
        return self._phase
