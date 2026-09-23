
import pytest

from quant.bars import Bar
from quant.contracts.contracts import ContractRef
from quant.events import BarClosed
from quant.execution.paper_simulator import PaperExecutionSimulator, PaperOrderStatus
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _contract():
    return ContractRef(
        symbol="NIFTY", exchange="NSE", expiry="2026-09-25",
        lot_size=25, tick_size=0.05,
    )


def test_paper_simulator_can_model_partial_entry_exposure():
    simulator = PaperExecutionSimulator(fill_mode="instant_mid", fill_ratio=0.4)
    fill = simulator.submit(
        order_id="entry-1", contract=_contract(), side="BUY", quantity=100,
        reference_price=100.0,
    )
    assert fill.status is PaperOrderStatus.PARTIALLY_FILLED
    assert fill.requested_quantity == 100
    assert fill.filled_quantity == 40


def test_paper_simulator_reject_mode_is_deterministic():
    simulator = PaperExecutionSimulator(fill_mode="instant_mid", order_mode="REJECT")
    with pytest.raises(RuntimeError, match="paper order rejected"):
        simulator.submit(
            order_id="entry-reject", contract=_contract(), side="BUY", quantity=25,
            reference_price=100.0,
        )


def test_paper_event_store_failure_marks_runtime_degraded_and_reconciliation_required(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=60)

    def fail_append(_event):
        raise OSError("disk full")

    monkeypatch.setattr(engine.event_store, "append", fail_append)
    engine._emit(BarClosed(symbol="NIFTY", time="2026-09-11T09:15:00+05:30", bar=Bar(time="2026-09-11T09:15:00+05:30")))

    assert engine.persistence_degraded is True
    assert engine.reconciliation_required is True
    assert engine.persistence_failure is not None
    assert engine.state.last_bar.time == "2026-09-11T09:15:00+05:30"


def test_non_paper_event_store_failure_does_not_mark_paper_degraded(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=60)

    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))
    engine._emit(BarClosed(symbol="NIFTY", time="2026-09-11T09:15:00+05:30", bar=Bar(time="2026-09-11T09:15:00+05:30")))

    assert not getattr(engine, "persistence_degraded", False)
    assert not getattr(engine, "reconciliation_required", False)


def test_paper_simulator_duplicate_partial_request_is_idempotent():
    simulator = PaperExecutionSimulator(fill_ratio=0.4)
    first = simulator.submit(
        order_id="entry-dup", contract=_contract(), side="BUY", quantity=100,
        reference_price=100.0,
    )
    second = simulator.submit(
        order_id="entry-dup", contract=_contract(), side="BUY", quantity=100,
        reference_price=101.0,
    )
    assert second == first
