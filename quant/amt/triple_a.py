"""Triple-A state machine — WAITING ⇄ AGGRESSION.

``AbsorptionDetector`` already holds the absorb bar pending until a later
candle closes beyond the cluster (spec §8 aggression). When it pulses
``SELL_ABSORBED`` / ``BUY_ABSORBED``, that bar *is* the aggression close.
This machine records that pulse for one bar, then returns to WAITING so
Gate 3 cannot sticky-ENTER.

``ABSORBING`` / ``ACCUMULATING`` remain part of the phase vocabulary the DTO,
gates and narrative label against, but the machine never dwells in them: a
detector-confirmed cluster close means absorption and accumulation have
already happened, so the pulse *is* the aggression bar.
"""

from __future__ import annotations

from dataclasses import dataclass

WAITING = "WAITING"
ABSORBING = "ABSORBING"
ACCUMULATING = "ACCUMULATING"
AGGRESSION = "AGGRESSION"

_PULSE_TO_SIGNAL = {"SELL_ABSORBED": "LONG", "BUY_ABSORBED": "SHORT"}


@dataclass(frozen=True)
class TripleASnapshot:
    phase: str = WAITING
    signal: str = ""
    cluster_high: float = 0.0
    cluster_low: float = 0.0
    conviction: float = 0.0


class TripleAMachine:
    """Detector-pulse machine: a confirmed absorption cluster close is the
    Playbook A aggression bar, recorded for exactly one bar.

    Only WAITING and AGGRESSION are reachable — the intermediate phases exist
    as vocabulary for the DTO/gate/narrative labels, not as dwell states.
    """

    def __init__(self) -> None:
        self._phase = WAITING
        self._signal = ""
        self._cluster_high = 0.0
        self._cluster_low = 0.0

    def reset(self) -> None:
        self._phase = WAITING
        self._signal = ""
        self._cluster_high = 0.0
        self._cluster_low = 0.0

    def snapshot(self) -> TripleASnapshot:
        return TripleASnapshot(
            phase=self._phase,
            signal=self._signal,
            cluster_high=self._cluster_high,
            cluster_low=self._cluster_low,
            conviction=1.0 if self._phase == AGGRESSION else 0.0,
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
        """Process one closed bar.

        ``close``, ``vwap`` and ``cvd_slope`` are accepted for call-site
        compatibility with the AMT analyzer; a detector pulse is authoritative
        and needs no further confirmation.
        """
        # A pulse lasts exactly one bar: clear the previous bar's AGGRESSION.
        if self._phase == AGGRESSION:
            self.reset()

        signal = _PULSE_TO_SIGNAL.get(absorption_side)
        if signal is not None:
            self._phase = AGGRESSION
            self._signal = signal
            self._cluster_high, self._cluster_low = high, low

        return self.snapshot()
