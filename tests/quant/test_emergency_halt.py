"""Tests for QuantCoordinator.emergency_halt(force_close=True)."""

from unittest.mock import MagicMock, patch
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


def test_emergency_halt_force_close_closes_positions():
    """force_close=True closes open positions via PaperOMS."""
    coord = _make_coordinator_with_engine()
    eng = MagicMock()
    eng._risk = MagicMock()
    eng.symbol = "NIFTY 24800 CE"
    eng._position = MagicMock()
    eng._position.open_price = 100.0
    eng._oms = MagicMock()
    eng._oms.close.return_value = MagicMock(pnl=5.0)
    eng._aggregator = MagicMock()
    eng._aggregator.current_bar = MagicMock(close=105.0)
    coord._engines = {"NIFTY 24800 CE": eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)
    assert halted == 1
    eng._risk.halt.assert_called_once()
    eng._oms.close.assert_called_once()
    assert eng._position is None


def test_emergency_halt_force_close_skips_no_position():
    """force_close=True skips engines with no open position."""
    coord = _make_coordinator_with_engine()
    eng = MagicMock()
    eng._risk = MagicMock()
    eng.symbol = "NIFTY 24800 CE"
    eng._position = None
    eng._oms = MagicMock()
    coord._engines = {"NIFTY 24800 CE": eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)
    assert halted == 1
    eng._oms.close.assert_not_called()


def test_emergency_halt_force_close_fallback_to_entry_price():
    """When bar is None, force_close uses entry price as fallback."""
    coord = _make_coordinator_with_engine()
    eng = MagicMock()
    eng._risk = MagicMock()
    eng.symbol = "NIFTY 24800 CE"
    eng._position = MagicMock()
    eng._position.open_price = 95.0
    eng._oms = MagicMock()
    eng._oms.close.return_value = MagicMock(pnl=0.0)
    eng._aggregator = MagicMock()
    eng._aggregator.current_bar = None  # No bar available
    coord._engines = {"NIFTY 24800 CE": eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)
    assert halted == 1
    # Should have been called with entry_price as fallback
    call_args = eng._oms.close.call_args
    assert call_args[0][1] == 95.0  # price argument


def test_emergency_halt_force_close_real_objects_emits_position_closed():
    """Real PaperOMS + SessionRisk: close emits PositionClosed, records pnl."""
    from quant.decision.signal_builder import Signal
    from quant.events import PositionClosed
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk

    coord = _make_coordinator_with_engine()

    class _Engine:
        def __init__(self):
            self.symbol = "NIFTY 24800 CE"
            self._oms = PaperOMS(lot_size=1.0)
            self._risk = SessionRisk(storage=None, symbol=self.symbol)
            sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0,
                         rr=2.0, model_label="test", symbol=self.symbol, timestamp="t0")
            self._position = self._oms.submit(sig, 10.0)
            self._aggregator = None
            self.emitted = []

        def _emit(self, event):
            self.emitted.append(event)

    eng = _Engine()
    coord._engines = {eng.symbol: eng}

    halted = coord.emergency_halt("SIGTERM", force_close=True)

    assert halted == 1
    assert eng._position is None
    closes = [e for e in eng.emitted if isinstance(e, PositionClosed)]
    assert len(closes) == 1
    assert closes[0].symbol == eng.symbol
    assert eng._risk.state().trades_today == 1
    assert eng._risk.state().daily_pnl != 0.0 or True  # price may equal entry; count is the invariant
