from __future__ import annotations

from quant.bars import Bar
from quant.events import BarClosed, PositionClosed, PositionOpened
from quant.events import PositionReduced, StopMoved
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


def test_failed_lifecycle_append_is_not_published_to_bus_or_journal(monkeypatch):
    engine = _engine(monkeypatch)
    observed = []
    engine._bus.subscribe(PositionOpened, observed.append)
    signal = Signal(type="LONG", reason="test", entry=100.0, sl=90.0, tp=120.0,
                    rr=2.0, model_label="test", symbol="NIFTY", timestamp="t1")
    position = Position(order=Order(signal=signal, quantity=1.0), open_price=100.0,
                         open_time="t1", size=1.0, _id="p-1")
    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))

    engine._emit(PositionOpened(symbol="NIFTY", time="t1", position=position))

    assert observed == []


def test_failed_reduce_and_close_appends_are_not_published(monkeypatch):
    engine = _engine(monkeypatch)
    observed = []
    engine._bus.subscribe(PositionReduced, observed.append)
    engine._bus.subscribe(PositionClosed, observed.append)
    signal = Signal(type="LONG", reason="test", entry=100.0, sl=90.0, tp=120.0,
                    rr=2.0, model_label="test", symbol="NIFTY", timestamp="t1")
    position = Position(order=Order(signal=signal, quantity=1.0), open_price=100.0,
                        open_time="t1", size=1.0, _id="p-1")
    fill = type("Fill", (), {"position": position, "order_id": "o-1", "pnl": 0.0})()
    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))

    engine._emit(PositionReduced(symbol="NIFTY", time="t1", fill=fill, remaining=position))
    engine._emit(PositionClosed(symbol="NIFTY", time="t1", fill=fill))

    assert observed == []


def test_failed_append_blocks_next_entry_in_every_execution_mode(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=60)
    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))
    signal = Signal(type="LONG", reason="test", entry=100.0, sl=90.0, tp=120.0,
                    rr=2.0, model_label="test", symbol="NIFTY", timestamp="t1")
    position = Position(order=Order(signal=signal, quantity=1.0), open_price=100.0,
                        open_time="t1", size=1.0, _id="p-1")
    engine._emit(PositionOpened(symbol="NIFTY", time="t1", position=position))
    assert engine._decision_loop._entry_guards(Bar(time="t2", close=100.0))[0] is True


def test_failed_append_keeps_non_lifecycle_operational_state(monkeypatch):
    engine = _engine(monkeypatch)
    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))
    engine._emit(BarClosed(symbol="NIFTY", time="t1", bar=Bar(time="t1", close=100.0)))

    assert engine.state.last_bar.time == "t1"
    assert engine.event_store.fold().last_bar is None


def test_stop_moved_is_appended_before_bus_publish(monkeypatch):
    """B-5: StopMoved must be durable before observers see it (append→publish)."""
    engine = _engine(monkeypatch)
    observed: list[str] = []
    order: list[str] = []
    engine._bus.subscribe(StopMoved, lambda _e: (order.append("publish"), observed.append("pub")))
    real_append = engine.event_store.append

    def tracking_append(event):
        order.append("append")
        return real_append(event)

    monkeypatch.setattr(engine.event_store, "append", tracking_append)

    engine._emit(StopMoved(symbol="NIFTY", time="t1", old_sl=99.0, new_sl=100.5,
                           reason="TRAIL_RATCHET", position_id="p-1"))

    assert observed == ["pub"], "StopMoved never published"
    assert order == ["append", "publish"], (
        f"StopMoved must append before publish, got {order}"
    )


def test_failed_stop_moved_append_is_not_published(monkeypatch):
    """A StopMoved that never hit the store must not reach bus/journal."""
    engine = _engine(monkeypatch)
    observed = []
    engine._bus.subscribe(StopMoved, observed.append)
    monkeypatch.setattr(engine.event_store, "append", lambda _event: (_ for _ in ()).throw(OSError("disk full")))

    engine._emit(StopMoved(symbol="NIFTY", time="t1", old_sl=99.0, new_sl=100.5,
                           reason="TRAIL_RATCHET", position_id="p-1"))

    assert observed == []
    assert engine.event_store.fold().position is None


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


def test_unmatched_position_close_is_replay_tolerant_and_diagnostic(caplog):
    from quant.state_machine import EngineState
    from quant.transitions import apply_event
    fill = type("Fill", (), {
        "position": type("Position", (), {"_id": "missing"})(),
        "order_id": "order-7", "pnl": 0.0,
    })()
    with caplog.at_level("WARNING", logger="quant.transitions"):
        state = apply_event(EngineState(symbol="NIFTY"), PositionClosed(
            symbol="NIFTY", time="t1", fill=fill,
        ))
    record = next(r for r in caplog.records if r.message == "unmatched lifecycle event")
    assert state.position is None
    assert record.event_type == "PositionClosed"
    assert record.order_id == "order-7"
