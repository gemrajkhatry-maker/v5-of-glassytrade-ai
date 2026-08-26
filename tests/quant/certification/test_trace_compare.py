"""Payload-exact trace comparison for replay determinism."""

from quant.events import BarClosed, PositionOpened
from quant.execution.order import Order, Position
from quant.decision.signal_builder import Signal
from tests.quant.certification.trace_compare import normalize, traces_equal


def _evt(event_id: str, corr: str) -> BarClosed:
    e = BarClosed(symbol="X", time="100", bar=None)
    object.__setattr__(e, "event_id", event_id)
    object.__setattr__(e, "correlation_id", corr)
    return e


def test_normalize_strips_volatile_ids():
    row = {"type": "BarClosed", "event_id": "7", "correlation_id": "u",
           "symbol": "X", "time": "100"}
    assert normalize(row) == {"type": "BarClosed", "symbol": "X", "time": "100"}


def test_normalize_strips_nested_position_uuid():
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0,
                 rr=2.0, model_label="T", symbol="X", timestamp="100")
    pos = Position(order=Order(signal=sig, quantity=10), open_price=100.0,
                   open_time="100", size=10)
    row = {"type": "PositionOpened", "position": pos.__dict__}
    norm = normalize(row)
    assert "_id" not in norm["position"]


def test_traces_equal_ignores_volatile_fields():
    a = [_evt("1", "ua"), _evt("2", "ub")]
    b = [_evt("9", "uz"), _evt("8", "uy")]
    assert traces_equal(a, b)


def test_traces_equal_detects_payload_drift():
    a = [_evt("1", "u")]
    b_evt = _evt("9", "u")
    b = [type(b_evt)(symbol="X", time="200", bar=None)]
    assert not traces_equal(a, b)
