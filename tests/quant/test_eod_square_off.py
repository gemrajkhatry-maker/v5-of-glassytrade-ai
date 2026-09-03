"""Tests for the EOD square-off backstop (intraday-only guarantee).

Every position must be closed at day end. The bar-driven SESSION_CLOSE
(Phase 5) handles normal operation; this backstop is the time-driven safety
net that force-flattens any still-open position once the market passes its
square-off deadline (exchange close - N min), independent of tick/bar flow.

Covers:
- QuantEngine.force_close_position: time-driven full close (base + pyramids),
  idempotent.
- QuantCoordinator.eod_square_off: flattens engines past their market's
  deadline, skips engines before deadline / with no open position.
- QuantCoordinator._squareoff_deadline: close - N min per market.
- QuantCoordinator._start_eod_watchdog: idempotent daemon thread.
"""

from unittest.mock import MagicMock
import threading

from quant.multi_engine import QuantCoordinator
from quant.runtime import QuantEngine


def _make_coord(eod_minutes: float = 15) -> QuantCoordinator:
    """Coordinator bypassing __init__ (mirrors test_emergency_halt helper)."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord.market_data = MagicMock()
    coord.broker = MagicMock()
    coord.config = {"exchange": "NSE", "eod_squareoff_minutes_before_close": eod_minutes}
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
    coord._eod_thread = None
    coord._lock = threading.Lock()
    coord._lifecycle_lock = threading.RLock()
    coord._portfolio_risk = MagicMock()
    coord.started = False
    return coord


def _open_engine(market: str = "NSE", has_position: bool = True) -> MagicMock:
    eng = MagicMock()
    eng.symbol = "NIFTY SEP FUT"
    eng._market = market
    eng.state = MagicMock()
    eng.state.position = MagicMock() if has_position else None
    eng._get_position_manager = MagicMock(return_value=MagicMock(pyramid_positions=[]))
    eng.force_close_position = MagicMock(return_value=True)
    return eng


# --- _squareoff_deadline ---------------------------------------------------

def test_squareoff_deadline_nse_close_minus_15():
    coord = _make_coord(eod_minutes=15)
    dl = coord._squareoff_deadline("NSE")
    # NSE close 15:30 IST - 15 min = 15:15 IST.
    assert (dl.hour, dl.minute) == (15, 15)


def test_squareoff_deadline_mcx_close_minus_15():
    coord = _make_coord(eod_minutes=15)
    dl = coord._squareoff_deadline("MCX")
    # MCX close 23:30 IST - 15 min = 23:15 IST.
    assert (dl.hour, dl.minute) == (23, 15)


def test_squareoff_deadline_respects_config_minutes():
    coord = _make_coord(eod_minutes=30)
    dl = coord._squareoff_deadline("NSE")
    assert (dl.hour, dl.minute) == (15, 0)


# --- eod_square_off --------------------------------------------------------

def test_eod_square_off_flattens_past_deadline():
    # 100000 min before close -> deadline far in the past -> always past it.
    coord = _make_coord(eod_minutes=100000)
    eng = _open_engine(has_position=True)
    coord._engines = {eng.symbol: eng}

    closed = coord.eod_square_off()

    assert closed == 1
    eng.force_close_position.assert_called_once_with("EOD_SQUARE_OFF")


def test_eod_square_off_skips_before_deadline():
    # -100000 min before close -> deadline far in the future -> not yet.
    coord = _make_coord(eod_minutes=-100000)
    eng = _open_engine(has_position=True)
    coord._engines = {eng.symbol: eng}

    closed = coord.eod_square_off()

    assert closed == 0
    eng.force_close_position.assert_not_called()


def test_eod_square_off_skips_engine_with_no_position():
    coord = _make_coord(eod_minutes=100000)
    eng = _open_engine(has_position=False)
    coord._engines = {eng.symbol: eng}

    closed = coord.eod_square_off()

    assert closed == 0
    eng.force_close_position.assert_not_called()


def test_eod_square_off_idempotent_after_flatten():
    """Once flattened (position None), a subsequent pass closes nothing."""
    coord = _make_coord(eod_minutes=100000)
    eng = _open_engine(has_position=True)
    coord._engines = {eng.symbol: eng}

    assert coord.eod_square_off() == 1
    # Simulate the flatten having cleared the position.
    eng.state.position = None
    eng.force_close_position.reset_mock()

    assert coord.eod_square_off() == 0
    eng.force_close_position.assert_not_called()


def test_eod_square_off_mixed_markets_only_flattens_past_due():
    """An MCX engine and NSE engine with the same config both flatten once
    their own market's deadline has passed (here: both forced past)."""
    coord = _make_coord(eod_minutes=100000)
    nse = _open_engine(market="NSE", has_position=True)
    mcx = _open_engine(market="MCX", has_position=True)
    mcx.symbol = "CRUDEOIL SEP FUT"
    coord._engines = {nse.symbol: nse, mcx.symbol: mcx}

    closed = coord.eod_square_off()

    assert closed == 2
    nse.force_close_position.assert_called_once()
    mcx.force_close_position.assert_called_once()


def test_eod_square_off_swallows_engine_errors():
    coord = _make_coord(eod_minutes=100000)
    good = _open_engine(has_position=True)
    bad = _open_engine(has_position=True)
    bad.symbol = "BANKNIFTY SEP FUT"
    bad.force_close_position = MagicMock(side_effect=RuntimeError("boom"))
    coord._engines = {good.symbol: good, bad.symbol: bad}

    closed = coord.eod_square_off()

    # The healthy engine still flattens even though the other raised.
    assert closed == 1
    good.force_close_position.assert_called_once()


# --- QuantEngine.force_close_position --------------------------------------

def _make_engine_stub() -> QuantEngine:
    eng = QuantEngine.__new__(QuantEngine)
    eng._close_lock = threading.Lock()
    eng.state = MagicMock()
    eng.state.position = None
    pm_mock = MagicMock()
    pm_mock.pyramid_positions = []
    pm_mock.current_position = None
    eng._get_position_manager = MagicMock(return_value=pm_mock)
    eng._aggregator = MagicMock()
    eng._portfolio_risk = None
    eng._bar_index = 0
    eng._last_close_bar_index = -1
    return eng


def test_force_close_position_no_position_returns_false():
    eng = _make_engine_stub()
    assert eng.force_close_position("EOD_SQUARE_OFF") is False


def test_force_close_position_closes_base_and_pyramids():
    from quant.decision.signal_builder import Signal
    from quant.events import PositionClosed
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    symbol = "NIFTY 24800 CE"
    oms = PaperOMS(lot_size=1.0)
    risk = SessionRisk(storage=None, symbol=symbol)
    emitted = []
    pm = PositionManager(
        oms=oms,
        exits=MagicMock(),  # pop_trail is a no-op for this test
        risk=risk,
        emit_fn=emitted.append,
        symbol=symbol,
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        portfolio_risk=None,
    )
    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0,
                 rr=2.0, model_label="test", symbol=symbol, timestamp="t0")
    base = oms.submit(sig, 10.0)
    # Build the add-on through the OMS pyramid path (is_pyramid=True) exactly
    # like the live flow, then fold its PositionOpened so the close matches.
    pyr = oms.add_pyramid(base=base, entry_price=101.0, new_sl=100.0,
                          size=5.0, time="t1", pyramid_level=1)
    pm.pyramid_positions = [pyr]
    pm.pyramid_count = 1
    pm.current_position = base

    eng = QuantEngine.__new__(QuantEngine)
    eng.symbol = symbol
    from quant.state_machine import EngineState, PositionState
    from quant.events import PositionOpened
    from quant.transitions import apply_event as _apply
    eng.state = EngineState(symbol=symbol, position=PositionState(
        id=base._id, entry=100.0, size=10.0, sl=99.0, tp=102.0, side="LONG"
    ))
    eng.state = _apply(
        eng.state, PositionOpened(symbol=symbol, time="t1", position=pyr)
    )
    eng._aggregator = MagicMock()
    eng._aggregator.current_bar = MagicMock(close=105.0)
    eng._portfolio_risk = None
    eng._open_trade_risk = 0.0
    eng._bar_index = 5
    eng._last_close_bar_index = -1
    eng._close_lock = threading.Lock()
    eng._bus = MagicMock()
    eng._trace = emitted  # Use emitted list to capture events
    eng._projector = MagicMock()
    eng._emit_lock = threading.Lock()
    eng.event_store = MagicMock()
    eng.event_store.append = lambda e: None
    eng._pos_mgr = pm
    # Wire the PositionManager's emit to go through engine's _emit
    pm._emit = eng._emit

    result = eng.force_close_position("EOD_SQUARE_OFF")

    assert result is True
    assert eng.state.position is None
    assert pm.pyramid_positions == []
    assert pm.pyramid_count == 0
    closes = [e for e in emitted if isinstance(e, PositionClosed)]
    # Base + 1 pyramid add-on = 2 PositionClosed events.
    assert len(closes) == 2
    # Idempotent: nothing left to close.
    assert eng.force_close_position("EOD_SQUARE_OFF") is False


def test_force_close_position_falls_back_to_entry_price_without_bar():
    from quant.decision.signal_builder import Signal
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    symbol = "NIFTY 24800 CE"
    oms = PaperOMS(lot_size=1.0)
    risk = SessionRisk(storage=None, symbol=symbol)
    emitted = []
    pm = PositionManager(
        oms=oms, exits=MagicMock(), risk=risk, emit_fn=emitted.append,
        symbol=symbol, market="NSE", contract_expiry=None,
        tick_size=0.05, portfolio_risk=None,
    )
    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0,
                 rr=2.0, model_label="test", symbol=symbol, timestamp="t0")
    base = oms.submit(sig, 10.0)
    pm.current_position = base

    eng = QuantEngine.__new__(QuantEngine)
    eng.symbol = symbol
    from quant.state_machine import EngineState, PositionState
    eng.state = EngineState(symbol=symbol, position=PositionState(
        id=base._id, entry=100.0, size=10.0, sl=99.0, tp=102.0, side="LONG"
    ))
    eng._aggregator = MagicMock()
    eng._aggregator.current_bar = None  # no forming bar -> entry-price fallback
    eng._portfolio_risk = None
    eng._open_trade_risk = 0.0
    eng._bar_index = 1
    eng._last_close_bar_index = -1
    eng._close_lock = threading.Lock()
    eng._bus = MagicMock()
    eng._trace = emitted  # Use emitted list to capture events
    eng._projector = MagicMock()
    eng._emit_lock = threading.Lock()
    eng.event_store = MagicMock()
    eng.event_store.append = lambda e: None
    eng._pos_mgr = pm
    # Wire the PositionManager's emit to go through engine's _emit
    pm._emit = eng._emit

    assert eng.force_close_position("EOD_SQUARE_OFF") is True
    assert eng.state.position is None
    # Closed at the entry price (100.0) since no forming bar was available.
    from quant.events import PositionClosed
    closes = [e for e in emitted if isinstance(e, PositionClosed)]
    assert len(closes) == 1
    assert float(closes[0].fill.close_price) == 100.0


# --- watchdog lifecycle ----------------------------------------------------

def test_start_eod_watchdog_is_idempotent():
    coord = _make_coord()
    coord._stop = threading.Event()
    coord._start_eod_watchdog()
    first = coord._eod_thread
    assert first is not None and first.is_alive()
    coord._start_eod_watchdog()
    assert coord._eod_thread is first  # no second thread spawned
    coord._stop.set()
    first.join(timeout=5)
    assert not first.is_alive()


def test_stop_joins_and_clears_watchdog():
    coord = _make_coord()
    coord._stop_engines = MagicMock()
    coord._feed = MagicMock()
    coord._start_eod_watchdog()
    assert coord._eod_thread is not None

    coord.stop()

    assert coord._eod_thread is None
    assert coord._stop.is_set()
    assert coord.started is False
