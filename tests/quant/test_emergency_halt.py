"""Tests for QuantCoordinator.emergency_halt(force_close=True)."""

from unittest.mock import MagicMock
import threading

from quant.multi_engine import QuantCoordinator


def _make_coordinator_with_engine():
    """Create a coordinator with a mocked engine that has an open position."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord.market_data = MagicMock()
    coord.broker = MagicMock()
    coord.config = {}
    coord._strategy = None
    coord._storage = None
    coord._contracts_file = "/tmp/.test_contracts.json"
    coord._session_levels = MagicMock()
    coord._feed = MagicMock()
    coord._engines = {}
    coord._gateways = {}
    coord._underlying_gateways = {}
    coord._threads = {}
    coord._stop = threading.Event()
    coord._lock = threading.Lock()
    coord._lifecycle_lock = threading.RLock()
    coord._portfolio_risk = MagicMock()
    coord.started = False
    return coord


def test_emergency_halt_hydrates_engines():
    """Basic halt increments counter for each engine with a risk attribute."""
    coord = _make_coordinator_with_engine()
    eng = MagicMock()
    eng._risk = MagicMock()
    eng.symbol = "NIFTY 24800 CE"
    coord._engines = {"NIFTY 24800 CE": eng}

    halted = coord.emergency_halt("test")
    assert halted == 1
    eng._risk.halt.assert_called_once_with("external/emergency: test")


def test_emergency_halt_force_close_delegates_to_engine_flatten():
    """C5: force_close=True must route through the engine's lock-serialized,
    pyramid-aware force_close_position — not a direct oms.close() that races
    the engine thread and skips pyramid add-ons."""
    coord = _make_coordinator_with_engine()
    eng = MagicMock()
    eng._risk = MagicMock()
    eng.symbol = "NIFTY 24800 CE"
    eng.force_close_position.return_value = True
    coord._engines = {"NIFTY 24800 CE": eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)
    assert halted == 1
    eng._risk.halt.assert_called_once()
    eng.force_close_position.assert_called_once()
    reason_arg = eng.force_close_position.call_args[0][0]
    assert "EMERGENCY_HALT" in reason_arg and "SIGTERM" in reason_arg


def test_emergency_halt_force_close_idempotent_when_nothing_open():
    """force_close=True on an engine with nothing open is a safe no-op (the
    engine's force_close_position returns False); risk is still halted."""
    coord = _make_coordinator_with_engine()
    eng = MagicMock()
    eng._risk = MagicMock()
    eng.symbol = "NIFTY 24800 CE"
    eng.force_close_position.return_value = False
    coord._engines = {"NIFTY 24800 CE": eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)
    assert halted == 1
    eng._risk.halt.assert_called_once()
    eng.force_close_position.assert_called_once()


def test_emergency_halt_force_close_real_engine_flattens():
    """C5: real QuantEngine + PaperOMS — emergency_halt(force_close=True) closes
    the position via force_close_position, emits PositionClosed, records the
    trade, and leaves no open position."""
    from quant.decision.signal_builder import Signal
    from quant.events import PositionClosed
    from quant.execution.oms import PaperOMS
    from quant.runtime import QuantEngine

    coord = _make_coordinator_with_engine()

    class _Gw:
        def subscribe(self, symbol):
            return

        def next_tick(self):
            return None

    eng = QuantEngine(_Gw(), "NIFTY 24800 CE", interval_seconds=1)
    eng._oms = PaperOMS(lot_size=1.0)
    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0,
                 rr=2.0, model_label="test", symbol="NIFTY 24800 CE", timestamp="t0")
    position = eng._oms.submit(sig, 10.0)
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(position))
    eng._get_position_manager().current_position = position
    emitted = []
    eng._bus.subscribe(PositionClosed, emitted.append)
    coord._engines = {eng.symbol: eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)

    assert halted == 1
    assert eng.state.position is None, "position must be flattened"
    closes = [e for e in emitted if isinstance(e, PositionClosed)]
    assert len(closes) == 1
    assert closes[0].symbol == eng.symbol
    assert eng._risk.state().trades_today == 1
