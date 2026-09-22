"""Stage 6 contract: kernel + exit cursor survive save/restore."""

from __future__ import annotations

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.orderflow.cvd import CVDTracker
from quant.amt.session.context import load_kernel_state, persist_kernel_state
from quant.amt.session_kernel import SessionKernel
from quant.decision.signal_builder import Signal
from quant.events import PositionOpened, PositionReduced
from quant.execution.exits import ExitEngine
from quant.execution.order import Fill, Order, Position
from quant.contracts.value_objects import OHLC
from quant.state_machine import EngineState
from quant.transitions import apply_event


def _candle(i: int, delta: float = 10.0) -> OHLC:
    return OHLC.create(
        time=f"2026-01-01T10:{i:02d}:00+05:30",
        open=100, high=101, low=99, close=100.5, volume=100.0, delta=delta,
        taker_buy_volume=55.0,
    )


def _position(*, size: float = 4.0, pid: str = "p1") -> Position:
    sig = Signal(
        type="LONG", reason="t", entry=100.0, sl=90.0, tp=120.0,
        rr=2.0, model_label="Triple-A", symbol="S", timestamp="t0",
    )
    return Position(
        order=Order(sig, size),
        open_price=100.0,
        open_time="t0",
        size=size,
        _id=pid,
    )


class _MemKV:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def kv_set(self, key: str, value: dict) -> None:
        self._data[key] = dict(value)

    def kv_get(self, key: str):
        return self._data.get(key)


def test_kernel_cvd_survives_export_import():
    analyzer = AMTAnalyzer()
    kernel = SessionKernel(analyzer)
    for i in range(20):
        analyzer._cvd_tracker.update(_candle(i))
        kernel.record_warm_bar()
    assert analyzer._cvd_tracker.value == 200.0
    snap = kernel.export_state()

    analyzer2 = AMTAnalyzer()
    kernel2 = SessionKernel(analyzer2)
    kernel2.import_state(snap)
    assert analyzer2._cvd_tracker.value == 200.0
    assert kernel2.warm_bars == 20
    assert float(getattr(analyzer2._ib_tracker, "ib_high", 0.0) or 0.0) == float(
        snap.get("ib_high") or 0.0
    )


def test_kernel_state_survives_kv_roundtrip():
    storage = _MemKV()
    analyzer = AMTAnalyzer()
    kernel = SessionKernel(analyzer)
    for i in range(10):
        analyzer._cvd_tracker.update(_candle(i))
        kernel.record_warm_bar()
    persist_kernel_state(storage, "NIFTY", kernel.export_state())

    analyzer2 = AMTAnalyzer()
    kernel2 = SessionKernel(analyzer2)
    kernel2.import_state(load_kernel_state(storage, "NIFTY"))
    assert analyzer2._cvd_tracker.value == analyzer._cvd_tracker.value
    assert kernel2.warm_bars == 10


def test_exit_cursor_tp_tier_survives_restore():
    eng = ExitEngine()
    pos = _position()
    eng.restore_stop_state(pos, breakeven=100.0, trail_stop=102.0, tp_tier=1)
    be, trail = eng.stop_state(pos)
    assert be == 100.0
    assert trail == 102.0
    assert eng._tp_tier.get(pos._id) == 1


def test_cvd_tracker_roundtrip_alone():
    t = CVDTracker()
    for i in range(10):
        t.update(_candle(i))
    data = t.export_state()
    t2 = CVDTracker()
    t2.import_state(data)
    assert t2.value == t.value
    assert t2.state().slope == t.state().slope


def test_pm_cache_matches_fold_after_lifecycle_events():
    """After every fill event fold, the execution book id/size match the fold."""

    class _PM:
        current_position = None

    def adopt(event, pm: _PM) -> None:
        if isinstance(event, PositionOpened):
            if int(getattr(event.position, "pyramid_level", 0) or 0) > 0:
                return
            pm.current_position = event.position
        elif isinstance(event, PositionReduced):
            pm.current_position = event.remaining

    pm = _PM()
    state = EngineState(symbol="S")
    opened = _position(size=4.0, pid="a")
    ev_open = PositionOpened(symbol="S", time="t0", position=opened)
    state = apply_event(state, ev_open)
    adopt(ev_open, pm)
    assert state.position is not None
    assert pm.current_position is not None
    assert pm.current_position._id == state.position.id
    assert abs(pm.current_position.size - state.position.size) < 1e-9

    remaining = _position(size=2.0, pid="a")
    partial = Fill(
        position=opened, close_price=110.0, close_time="t1", reason="TP1", pnl=20.0,
    )
    ev_red = PositionReduced(symbol="S", time="t1", fill=partial, remaining=remaining)
    state = apply_event(state, ev_red)
    adopt(ev_red, pm)
    assert state.position is not None
    assert pm.current_position is not None
    assert pm.current_position._id == state.position.id
    assert abs(pm.current_position.size - state.position.size) < 1e-9
