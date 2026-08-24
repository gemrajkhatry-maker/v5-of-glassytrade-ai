"""AMT scanner — multi-instrument setup discovery over the pure kernel.

Runs one :class:`AMTKernel` per instrument over its recent bars and ranks the
final snapshots by setup strength (completed Triple-A first, then
accumulation/absorption). Purely analysis-level: it surfaces candidates; the
strategy decides. Deterministic: same bars -> same ranking.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tradex_domain.instruments import Instrument
from tradex_domain.market import Candle

from tradex_trading.strategy.extensions.amt.kernel import AMTKernel
from tradex_trading.strategy.extensions.amt.model import AMTPhase, AMTSnapshot, AMTStrategyConfig


@dataclass(frozen=True, slots=True)
class AMTScanResult:
    instrument: Instrument
    phase: str
    direction: str | None
    setup: str
    score: float
    absorption_side: str | None
    absorption_strength: Decimal
    timestamp: datetime | None


class AMTScanner:
    def __init__(self, config: AMTStrategyConfig | None = None) -> None:
        self.config = config or AMTStrategyConfig()

    def scan(
        self,
        universes: Sequence[tuple[Instrument, Sequence[Candle]]],
    ) -> list[AMTScanResult]:
        """Rank instruments by their latest AMT snapshot setup strength.

        ``Instrument`` is not hashable (its metadata carries a mutable
        ``extra`` dict), so the universe is an explicit ordered sequence of
        ``(instrument, candles)`` pairs.
        """
        results: list[AMTScanResult] = []
        for instrument, candles in universes:
            if not candles:
                continue
            kernel = AMTKernel(self.config)
            snapshot: AMTSnapshot | None = None
            for candle in candles:
                snapshot = kernel.update(candle)
            if snapshot is None:
                continue
            score, setup = self._score(snapshot)
            if score <= 0:
                continue
            results.append(AMTScanResult(
                instrument=instrument,
                phase=snapshot.phase.value,
                direction=snapshot.direction,
                setup=setup,
                score=score,
                absorption_side=snapshot.absorption_side,
                absorption_strength=snapshot.absorption_strength,
                timestamp=snapshot.timestamp,
            ))
        results.sort(key=lambda r: (-r.score, r.instrument.symbol))
        return results

    @staticmethod
    def _score(snapshot: AMTSnapshot) -> tuple[float, str]:
        return score_snapshot(snapshot)


def score_snapshot(snapshot: AMTSnapshot) -> tuple[float, str]:
    """Rank a snapshot's setup strength; shared by the scanner and the live
    read-side AMTService projection."""
    if snapshot.phase is AMTPhase.AGGRESSION and snapshot.direction:
        return 100.0 + float(snapshot.absorption_strength) * 20.0, "TRIPLE_A"
    if snapshot.phase is AMTPhase.ACCUMULATING:
        return 60.0, "ACCUMULATING"
    if snapshot.phase is AMTPhase.ABSORBING and snapshot.absorption_side:
        return 40.0, "ABSORBING"
    if snapshot.absorption_side and snapshot.absorption_strength > 0:
        return 30.0, "ABSORPTION"
    return 0.0, ""


__all__ = ["AMTScanner", "AMTScanResult", "score_snapshot"]
