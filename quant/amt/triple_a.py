"""Triple-A state machine — WAITING → ABSORBING → ACCUMULATING → AGGRESSION.

``AbsorptionDetector`` already holds the absorb bar pending until a later
candle closes beyond the cluster (spec §8 aggression). When it pulses
``SELL_ABSORBED`` / ``BUY_ABSORBED``, that bar *is* the aggression close.
This machine records that pulse for one bar, then returns to WAITING so
Gate 3 cannot sticky-ENTER.

Conviction decays over time: each bar without progress reduces conviction.
After _STALE_BARS bars with no advancement, conviction hits 0 and the
machine resets to WAITING — preventing stale setups from being taken.
"""

from __future__ import annotations

from dataclasses import dataclass

WAITING = "WAITING"
ABSORBING = "ABSORBING"
ACCUMULATING = "ACCUMULATING"
AGGRESSION = "AGGRESSION"

_STALE_BARS = 15
_ACCUM_BARS = 2
_CONVICTION_DECAY = 0.05  # per bar without progress


@dataclass(frozen=True)
class TripleASnapshot:
    phase: str = WAITING
    signal: str = ""
    cluster_high: float = 0.0
    cluster_low: float = 0.0
    conviction: float = 0.0


class TripleAMachine:
    """Sequential absorption → accumulation → aggression. Never skip a phase
    unless the detector already confirmed cluster close (aggression pulse).

    Conviction starts at 0, increases on phase advancement, and decays
    each bar without progress. A setup with decaying conviction will
    eventually reset to WAITING — preventing stale entries.
    """

    def __init__(self) -> None:
        self._phase = WAITING
        self._signal = ""
        self._cluster_high = 0.0
        self._cluster_low = 0.0
        self._bars = 0
        self._conviction = 0.0

    def reset(self) -> None:
        self._phase = WAITING
        self._signal = ""
        self._cluster_high = 0.0
        self._cluster_low = 0.0
        self._bars = 0
        self._conviction = 0.0

    def snapshot(self) -> TripleASnapshot:
        return TripleASnapshot(
            phase=self._phase,
            signal=self._signal,
            cluster_high=self._cluster_high,
            cluster_low=self._cluster_low,
            conviction=self._conviction,
        )

    def update(
        self,
        *,
        close: float,
        high: float,
        low: float,
        absorption_side: str,
        vwap: float = 0.0,
        cvd_slope: float = 0.0,
    ) -> TripleASnapshot:
        if self._phase == AGGRESSION:
            self.reset()

        # Detector-confirmed cluster close: this bar is Playbook A aggression.
        if absorption_side == "SELL_ABSORBED":
            self._phase = AGGRESSION
            self._signal = "LONG"
            self._cluster_high, self._cluster_low = high, low
            self._conviction = 1.0
            return self.snapshot()
        if absorption_side == "BUY_ABSORBED":
            self._phase = AGGRESSION
            self._signal = "SHORT"
            self._cluster_high, self._cluster_low = high, low
            self._conviction = 1.0
            return self.snapshot()

        if self._phase == WAITING:
            return self.snapshot()

        # Unconfirmed path: absorb bar seen via some other feed, wait for close.
        self._bars += 1

        # Conviction decay: each bar without progress reduces conviction
        self._conviction = max(0.0, self._conviction - _CONVICTION_DECAY)

        if self._bars > _STALE_BARS or self._conviction <= 0.0:
            self.reset()
            return self.snapshot()

        prev_phase = self._phase
        if self._phase == ABSORBING and self._bars >= _ACCUM_BARS:
            self._phase = ACCUMULATING
            self._bars = 0
            self._conviction = min(1.0, self._conviction + 0.3)
            return self.snapshot()

        if self._phase == ACCUMULATING:
            if self._signal == "LONG" and close > self._cluster_high:
                if (vwap <= 0 or close > vwap) and cvd_slope > -0.2:
                    self._phase = AGGRESSION
                    self._conviction = 1.0
            elif self._signal == "SHORT" and close < self._cluster_low:
                if (vwap <= 0 or close < vwap) and cvd_slope < 0.2:
                    self._phase = AGGRESSION
                    self._conviction = 1.0

        # If phase didn't advance, conviction continues to decay
        if self._phase == prev_phase:
            self._conviction = max(0.0, self._conviction - _CONVICTION_DECAY)

        return self.snapshot()
