import pytest

from quant.contracts.contracts import ContractRef
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.oms import PaperOMS
from quant.execution.paper_simulator import PaperExecutionSimulator


def _sig(direction="LONG"):
    return Signal(type=direction, reason="Triple-A", entry=100.0, sl=99.0,
                  tp=102.0, rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")


def _contract():
    return ContractRef(
        symbol="SYM",
        exchange="NFO",
        expiry="2026-09-30",
        lot_size=65,
        tick_size=0.05,
    )


def test_submit_long():
    oms = PaperOMS()
    p = oms.submit(_sig(), quantity=10)
    assert p.size == 10 and p.open_price == 100.0
    assert p.order.signal.type == "LONG"


def test_submit_short_is_negative_size():
    oms = PaperOMS()
    p = oms.submit(_sig("SHORT"), quantity=5)
    assert p.size == -5


def test_close_long_profit():
    oms = PaperOMS()
    p = oms.submit(_sig(), quantity=10)
    f = oms.close(p, price=102.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((102 - 100) * 10)
    assert f.reason == "TP"


def test_close_short_profit():
    oms = PaperOMS()
    p = oms.submit(_sig("SHORT"), quantity=5)
    f = oms.close(p, price=99.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((100 - 99) * 5)


# ---------------------------------------------------------------------------
# Lot-aware sizing — paper P&L must match live rupee P&L exactly
# ---------------------------------------------------------------------------


def test_submit_snaps_size_to_lot_multiples():
    """100 raw units / 65 lot -> round(1.54) = 2 lots = 130 units, exactly the
    rounding the live adapter (DhanBrokerAdapter._resolve_quantity) and
    Portfolio.open_position apply."""
    oms = PaperOMS(lot_size=65)
    p = oms.submit(_sig(), quantity=100)
    assert p.size == 130
    assert p.order.quantity == 130


def test_submit_enforces_minimum_one_lot():
    oms = PaperOMS(lot_size=65)
    p = oms.submit(_sig(), quantity=10)
    assert p.size == 65


def test_submit_short_snaps_to_negative_lot_multiple():
    oms = PaperOMS(lot_size=65)
    p = oms.submit(_sig("SHORT"), quantity=100)
    assert p.size == -130


def test_close_pnl_is_lot_scaled():
    """pnl = price_diff * (lot-snapped units) — the same unit count a live
    fill would report, so paper and live rupee P&L agree."""
    oms = PaperOMS(lot_size=65)
    p = oms.submit(_sig(), quantity=100)  # snapped to 130 units
    f = oms.close(p, price=102.0, time="t1", reason="TP")
    assert f.pnl == pytest.approx((102 - 100) * 130)
    assert f.pnl == pytest.approx((102 - 100) * 100 * 1.3)  # 130 = 2 lots


def test_lot_size_one_preserves_legacy_behavior():
    oms = PaperOMS(lot_size=1)
    p = oms.submit(_sig(), quantity=10)
    f = oms.close(p, price=102.0, time="t1", reason="TP")
    assert p.size == 10
    assert f.pnl == pytest.approx((102 - 100) * 10)


def test_paper_oms_can_use_authoritative_simulator_fill():
    simulator = PaperExecutionSimulator()
    oms = PaperOMS(
        lot_size=65,
        simulator=simulator,
        contract=_contract(),
    )

    position = oms.submit(_sig(), quantity=65)

    assert position.open_price == 100.0
    assert oms.last_fill is not None
    assert oms.last_fill.filled_quantity == 65
    assert simulator.fills[0].instrument_key.startswith("NFO:")


def test_paper_oms_simulator_close_uses_actual_fill():
    simulator = PaperExecutionSimulator()
    oms = PaperOMS(
        lot_size=65,
        simulator=simulator,
        contract=_contract(),
    )
    position = oms.submit(_sig(), quantity=65)

    fill = oms.close(position, price=102.0, time="t1", reason="TP")

    assert fill.close_price == 102.0
    assert fill.pnl == pytest.approx(130.0)
    assert len(simulator.fills) == 2
