"""Decision-gate tests: stop cushioning and pyramiding (Fabio spec)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import Equity

from tradex_trading.strategy.extensions.amt.gates import AMTDecisionContext, evaluate
from tradex_trading.strategy.extensions.amt.model import AMTPhase, AMTSnapshot

INSTRUMENT = Equity.of("NSE", "RELIANCE")


def _snapshot(**changes: object) -> AMTSnapshot:
    values = dict(
        instrument=INSTRUMENT,
        timestamp=datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
        close=Decimal("102"), poc=Decimal("100"), vah=Decimal("103"),
        val=Decimal("99"), vwap=Decimal("100"), upper_1=Decimal("101"),
        lower_1=Decimal("99"), upper_2=Decimal("102"), lower_2=Decimal("98"),
        vwap_std=Decimal("1"), delta=Decimal("10"), cvd=Decimal("10"),
        cvd_slope=Decimal("1"), cvd_divergence="NONE", absorption_side="BUY",
        absorption_strength=Decimal("0.8"), absorption_age=1,
        ib_high=Decimal("103"), ib_low=Decimal("98"), ib_complete=True,
        location="ABOVE_VA", nearest_level=Decimal("103"),
        profile_shape="p_shape", lvn_levels=(), hvn_levels=(),
        phase=AMTPhase.AGGRESSION, direction="LONG",
    )
    values.update(changes)
    return AMTSnapshot(**values)


def test_long_stop_is_cushioned_beyond_structural_level() -> None:
    decision = evaluate(
        AMTDecisionContext(snapshot=_snapshot(), stop_cushion=Decimal("0.1"))
    )

    assert decision.approved is True
    # Structural stop = VAL (99); cushion pushes it 0.1 lower.
    assert decision.stop_loss == Decimal("98.9")
    assert decision.cushion == Decimal("0.1")
    assert decision.stop_loss < decision.entry < decision.take_profit


def test_short_stop_is_cushioned_beyond_structural_level() -> None:
    snapshot = _snapshot(
        close=Decimal("98"), direction="SHORT", location="BELOW_VA",
        vah=Decimal("100"), val=Decimal("97"), upper_1=Decimal("100"),
        lower_1=Decimal("98"), lower_2=Decimal("97"),
    )
    decision = evaluate(
        AMTDecisionContext(snapshot=snapshot, stop_cushion=Decimal("0.1"))
    )

    assert decision.approved is True
    # Structural stop = VAH (100); cushion pushes it 0.1 higher.
    assert decision.stop_loss == Decimal("100.1")
    assert decision.cushion == Decimal("0.1")


def test_zero_cushion_keeps_structural_stop() -> None:
    decision = evaluate(AMTDecisionContext(snapshot=_snapshot()))

    assert decision.approved is True
    assert decision.stop_loss == Decimal("99")
    assert decision.cushion == Decimal("0")


def test_pyramid_allowed_with_same_direction_and_strong_aggression() -> None:
    snapshot = _snapshot(aggression_score=Decimal("5"))
    decision = evaluate(
        AMTDecisionContext(
            snapshot=snapshot,
            position_open=True,
            position_direction="LONG",
        )
    )

    assert decision.approved is True
    assert decision.setup == "PYRAMID"
    assert decision.pyramid is True


def test_pyramid_blocked_when_position_is_opposite_direction() -> None:
    snapshot = _snapshot(aggression_score=Decimal("5"))
    decision = evaluate(
        AMTDecisionContext(
            snapshot=snapshot,
            position_open=True,
            position_direction="SHORT",
        )
    )

    assert decision.approved is False
    assert "position_open" in decision.failed_gates


def test_pyramid_blocked_without_aggression_score() -> None:
    snapshot = _snapshot(aggression_score=Decimal("1"))
    decision = evaluate(
        AMTDecisionContext(
            snapshot=snapshot,
            position_open=True,
            position_direction="LONG",
        )
    )

    assert decision.approved is False
    assert "position_open" in decision.failed_gates


def test_pyramid_blocked_when_disabled() -> None:
    snapshot = _snapshot(aggression_score=Decimal("5"))
    decision = evaluate(
        AMTDecisionContext(
            snapshot=snapshot,
            position_open=True,
            position_direction="LONG",
            pyramid_enabled=False,
        )
    )

    assert decision.approved is False


def test_plain_entry_still_blocked_while_position_open() -> None:
    snapshot = _snapshot(aggression_score=Decimal("1"))
    decision = evaluate(
        AMTDecisionContext(
            snapshot=snapshot,
            position_open=True,
            position_direction="LONG",
        )
    )

    assert decision.approved is False
