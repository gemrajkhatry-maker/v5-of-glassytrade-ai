from __future__ import annotations

from quant.bars import Bar
from quant.events import BarClosed, PositionOpened
from quant.events import PositionReduced
from quant.execution.order import Order, Position
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _engine(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    return QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=60)


def test_failed_position_open_append_does_not_advance_canonical_state(monkeypatch):
    engine = _engine(monkeypatch)
    signal = Signal(type="LONG", reason="test", entry=100.0, sl=90.0, tp=120.0,
                    rr=2.0, model_label="test", symbol="NIFTY", timestamp="t1")
    position = Position(order=Order(signal=signal, quantity=1.0), open_price=100.0,
                        open_time="t1", size=1.0, _id="p-1")

    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))
    engine._emit(PositionOpened(symbol="NIFTY", time="t1", position=position))

    assert engine.event_store.fold().position is None
    assert engine.persistence_degraded is True
    assert engine.reconciliation_required is True


def test_failed_append_keeps_non_lifecycle_operational_state(monkeypatch):
    engine = _engine(monkeypatch)
    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))
    engine._emit(BarClosed(symbol="NIFTY", time="t1", bar=Bar(time="t1", close=100.0)))

    assert engine.state.last_bar.time == "t1"
    assert engine.event_store.fold().last_bar is None


def test_unmatched_reduction_emits_structured_replay_diagnostic(caplog):
    from quant.state_machine import EngineState
    from quant.transitions import apply_event
    fill = type("Fill", (), {"position": type("Position", (), {"_id": "missing"})()})()
    with caplog.at_level("WARNING", logger="quant.transitions"):
        apply_event(EngineState(symbol="NIFTY"), PositionReduced(
            symbol="NIFTY", time="t1", fill=fill, remaining=fill.position,
        ))

    record = next(r for r in caplog.records if r.message == "unmatched lifecycle event")
    assert record.event_type == "PositionReduced"
    assert record.symbol == "NIFTY"
    assert record.position_id == "missing"
    assert record.sequence == 1
