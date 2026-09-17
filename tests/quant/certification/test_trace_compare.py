"""Payload-exact trace comparison for replay determinism."""

from quant.events import BarClosed
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
    row = {"type": "PositionOpened",
           "position": {"_id": "pos-uuid", "size": 10,
                        "order": {"quantity": 10,
                                  "signal": {"entry": 100.0}}}}
    norm = normalize(row)
    assert "_id" not in norm["position"]
    assert norm["position"]["order"]["signal"]["entry"] == 100.0


def test_normalize_strips_stop_moved_position_id():
    """position_id is a run-local uuid, not behaviour — it must not diverge."""
    from quant.events import StopMoved
    from tests.quant.certification.trace_compare import traces_equal

    a = [StopMoved(symbol="X", time="100", old_sl=99.0, new_sl=100.0,
                   reason="BREAKEVEN_ARMED", position_id="uuid-a", stop_kind="TRAIL")]
    b = [StopMoved(symbol="X", time="100", old_sl=99.0, new_sl=100.0,
                   reason="BREAKEVEN_ARMED", position_id="uuid-b", stop_kind="TRAIL")]
    assert traces_equal(a, b)
    assert "position_id" not in normalize({"position_id": "uuid-a", "new_sl": 100.0})


def test_traces_equal_ignores_volatile_fields():
    a = [_evt("1", "ua"), _evt("2", "ub")]
    b = [_evt("9", "uz"), _evt("8", "uy")]
    assert traces_equal(a, b)


def test_traces_equal_detects_payload_drift():
    a = [_evt("1", "u")]
    b_evt = _evt("9", "u")
    b = [type(b_evt)(symbol="X", time="200", bar=None)]
    assert not traces_equal(a, b)


class TestStrictEquality:
    def test_int_vs_float_is_divergence(self):
        from tests.quant.certification.trace_compare import _strict_eq
        assert not _strict_eq({"qty": 10}, {"qty": 10.0})
        assert not _strict_eq({"halted": True}, {"halted": 1})
        assert not _strict_eq({"v": None}, {"other": None})
        assert _strict_eq({"a": {"b": (1, "x")}}, {"a": {"b": (1, "x")}})
