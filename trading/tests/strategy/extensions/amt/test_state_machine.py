from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import Equity

from tradex_trading.strategy.extensions.amt.model import AMTPhase, AMTSnapshot
from tradex_trading.strategy.extensions.amt.state_machine import TripleAStateMachine

INSTRUMENT = Equity.of("NSE", "RELIANCE")


def _snapshot(**changes: object) -> AMTSnapshot:
    base = AMTSnapshot(
        instrument=INSTRUMENT,
        timestamp=datetime(2026, 8, 1, 9, 20, tzinfo=UTC),
        close=Decimal("100"), poc=Decimal("100"), vah=Decimal("102"),
        val=Decimal("98"), vwap=Decimal("100"), upper_1=Decimal("101"),
        lower_1=Decimal("99"), upper_2=Decimal("102"), lower_2=Decimal("98"),
        vwap_std=Decimal("1"), delta=Decimal("0"), cvd=Decimal("0"),
        cvd_slope=Decimal("0"), cvd_divergence="NONE", absorption_side=None,
        absorption_strength=Decimal("0"), absorption_age=None,
        ib_high=Decimal("102"), ib_low=Decimal("98"), ib_complete=True,
        location="INSIDE_VA", nearest_level=Decimal("100"),
        profile_shape="d_shape", lvn_levels=(), hvn_levels=(),
    )
    return replace(base, **changes)


def test_triple_a_progresses_without_skipping_phases() -> None:
    machine = TripleAStateMachine(accumulation_bars=2)

    assert machine.update(_snapshot()).phase is AMTPhase.WAITING
    absorbing = _snapshot(
        absorption_side="BUY", absorption_strength=Decimal("0.8")
    )
    assert machine.update(absorbing).phase is AMTPhase.ABSORBING
    assert machine.update(absorbing).phase is AMTPhase.ACCUMULATING
    result = machine.update(
        _snapshot(
            close=Decimal("102"),
            absorption_side="BUY",
            absorption_strength=Decimal("0.8"),
            upper_1=Decimal("101"),
        )
    )

    assert result.phase is AMTPhase.AGGRESSION
    assert result.direction == "LONG"


def test_triple_a_cannot_skip_from_waiting_to_aggression() -> None:
    machine = TripleAStateMachine()

    result = machine.update(_snapshot(close=Decimal("105"), upper_1=Decimal("101")))

    assert result.phase is AMTPhase.WAITING
    assert result.direction is None


def test_short_path_is_symmetric() -> None:
    machine = TripleAStateMachine(accumulation_bars=1)
    machine.update(_snapshot())
    absorbing = _snapshot(
        absorption_side="SELL", absorption_strength=Decimal("0.8")
    )
    machine.update(absorbing)
    machine.update(absorbing)
    result = machine.update(
        _snapshot(
            close=Decimal("97"),
            lower_1=Decimal("99"),
            absorption_side="SELL",
            absorption_strength=Decimal("0.8"),
        )
    )

    assert result.phase is AMTPhase.AGGRESSION
    assert result.direction == "SHORT"
