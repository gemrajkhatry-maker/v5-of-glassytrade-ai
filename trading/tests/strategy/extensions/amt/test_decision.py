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


def test_triple_a_decision_builds_structural_stop_and_target() -> None:
    decision = evaluate(AMTDecisionContext(snapshot=_snapshot()))

    assert decision.approved is True
    assert decision.setup == "TRIPLE_A"
    assert decision.direction == "LONG"
    assert decision.stop_loss < decision.entry < decision.take_profit
    assert decision.risk_reward >= Decimal("1.5")


def test_position_and_cooldown_gates_fail_closed() -> None:
    snapshot = _snapshot()
    assert evaluate(AMTDecisionContext(snapshot=snapshot, position_open=True)).approved is False
    assert evaluate(AMTDecisionContext(snapshot=snapshot, cooldown_bars=1)).approved is False


def test_value_area_fade_is_secondary_setup() -> None:
    snapshot = _snapshot(
        close=Decimal("99"), phase=AMTPhase.WAITING, direction=None,
        location="BELOW_VA", absorption_side=None, delta=Decimal("12"),
    )
    decision = evaluate(AMTDecisionContext(snapshot=snapshot))

    assert decision.approved is True
    assert decision.setup == "VA_FADE"
    assert decision.direction == "LONG"
