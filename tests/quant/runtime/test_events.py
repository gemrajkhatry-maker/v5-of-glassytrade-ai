# tests/quant/runtime/test_events.py
from quant.events import EventBus, BarClosed, PositionClosed
from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position, Fill


def _bar(time="t1"):
    return Bar(time=time, open=100, high=101, low=99, close=100, volume=100)


def _fill():
    sig = Signal(type="LONG", reason="test", entry=100.0, sl=99.0,
                 tp=102.0, rr=2.0, confidence=0.7, symbol="S", timestamp="t1")
    pos = Position(order=Order(signal=sig, quantity=10), open_price=100.0,
                   open_time="t1", size=10.0)
    return Fill(position=pos, close_price=101.0, close_time="t2",
                reason="TP", pnl=10.0)


def test_bus_dispatches_by_type():
    bus = EventBus()
    got = []
    bus.subscribe(BarClosed, lambda e: got.append(e.bar.time))
    bus.publish(BarClosed(symbol="S", time="t1", bar=_bar("t1")))
    assert got == ["t1"]


def test_bus_ignores_unrelated_types():
    bus = EventBus()
    got = []
    bus.subscribe(BarClosed, lambda e: got.append(1))
    bus.publish(PositionClosed(symbol="S", time="t", fill=_fill()))
    assert got == []


def test_multiple_handlers_in_order():
    bus = EventBus()
    order = []
    bus.subscribe(BarClosed, lambda e: order.append("a"))
    bus.subscribe(BarClosed, lambda e: order.append("b"))
    bus.publish(BarClosed(symbol="S", time="t", bar=_bar("t")))
    assert order == ["a", "b"]


def test_subscription_is_per_exact_type():
    bus = EventBus()
    got = []
    bus.subscribe(PositionClosed, lambda e: got.append(e.fill.pnl))
    bus.publish(PositionClosed(symbol="S", time="t2", fill=_fill()))
    bus.publish(BarClosed(symbol="S", time="t", bar=_bar("t")))
    assert got == [10.0]
