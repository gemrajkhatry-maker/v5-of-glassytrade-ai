# tests/quant/runtime/test_tick_level_exits.py
import pytest
from quant.brokers.gateway import Tick
from quant.events import PositionClosed
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0):
    return Signal(
        type=side,
        reason="Triple-A setup",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=2.0,
        model_label="Triple-A",
        symbol=symbol,
        timestamp="1700000000",
    )


def test_tick_level_sl_breach_closes_position_immediately():
    """When a tick price crosses the stop loss level, position is closed immediately on tick."""
    ticks = [
        Tick(time="1700000000", price=100.0, volume=10, buy_volume=5, sell_volume=5),
        Tick(time="1700000010", price=89.0, volume=10, buy_volume=0, sell_volume=10),
    ]
    gw = SyntheticGateway(ticks)
    eng = QuantEngine(gw, "TEST", interval_seconds=300)
    
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    eng._position = eng._oms.submit(sig, 1.0)
    eng._entry_bar_index = 0
    
    events = eng.run()
    
    closed_events = [e for e in events if isinstance(e, PositionClosed)]
    assert len(closed_events) == 1
    assert closed_events[0].time == "1700000010"
    assert closed_events[0].fill.reason == "SL"
    assert closed_events[0].fill.close_price == 89.0
    assert eng._position is None


def test_tick_level_tp_hit_closes_position_immediately():
    """When a tick price crosses the take profit level, position is closed immediately on tick."""
    ticks = [
        Tick(time="1700000000", price=100.0, volume=10, buy_volume=5, sell_volume=5),
        Tick(time="1700000010", price=121.0, volume=10, buy_volume=10, sell_volume=0),
    ]
    gw = SyntheticGateway(ticks)
    eng = QuantEngine(gw, "TEST", interval_seconds=300)
    
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    eng._position = eng._oms.submit(sig, 1.0)
    eng._entry_bar_index = 0
    
    events = eng.run()
    
    closed_events = [e for e in events if isinstance(e, PositionClosed)]
    assert len(closed_events) == 1
    assert closed_events[0].time == "1700000010"
    assert closed_events[0].fill.reason == "TP"
    assert closed_events[0].fill.close_price == 121.0
    assert eng._position is None


def _make_pm():
    oms = PaperOMS(lot_size=1.0)
    exits = ExitEngine()
    pm = PositionManager(
        oms=oms,
        exits=exits,
        risk=SessionRisk(starting_equity=1_000_000),
        emit_fn=lambda e: None,
        symbol="TEST",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
    )
    return pm, oms


def test_tick_tp_touch_books_first_partial_not_full_close():
    """An intrabar touch of signal.tp on the tick path books half + arms BE
    (bar-path parity), instead of silently full-closing the plan."""
    pm, oms = _make_pm()
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    open_position = oms.submit(sig, 4.0)
    assert open_position.size == 4

    out = pm.manage_tick_exit(open_position, tick_price=120.0, tick_time="12:00:00")

    assert out is not None                      # still alive
    assert out.size == 2                        # half booked
    assert pm._exits._tp_tier[open_position._id] == 1    # tier armed
    assert pm._exits._breakeven[open_position._id] == pytest.approx(100.0)


def test_tick_tp_second_touch_closes_remaining_runner():
    """After TP1 books the half, a TP2 tag closes the runner (size→0).

    Runner parity with the bar path (Rule 4): tier>=1 waits for
    TP2 = entry ± 2*(tp−entry), NOT another sig_tp tag."""
    pm, oms = _make_pm()
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    open_position = oms.submit(sig, 4.0)

    remaining = pm.manage_tick_exit(open_position, tick_price=120.0, tick_time="12:00:00")
    assert remaining is not None and remaining.size == 2

    out = pm.manage_tick_exit(remaining, tick_price=140.0, tick_time="12:00:01")
    assert out is None                           # runner closed at TP2
    assert pm.last_fill is not None and pm.last_fill.reason == "TP2"
    assert pm._exits._tp_tier.get(open_position._id) is None  # state released


def test_tick_tp_touch_records_partial_pnl_in_risk():
    """Tick-path TP1 must book the partial P&L into SessionRisk (bar-path
    parity) — daily_pnl drives the cushion/halt risk core, so dropping it
    understates risk for tick-path scalps."""
    pm, oms = _make_pm()
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    open_position = oms.submit(sig, 4.0)

    out = pm.manage_tick_exit(open_position, tick_price=120.0, tick_time="12:00:00")

    assert out is not None and out.size == 2
    assert pm.last_partial_fill is not None      # bar-path parity: partial is journaled
    assert pm._risk._daily_pnl == pytest.approx((120.0 - 100.0) * 2.0)


# ---------------------------------------------------------------------------
# Runner (tier>=1) TP geometry — bar parity (audit round 2, Task 2)
# ---------------------------------------------------------------------------

@pytest.fixture
def pm():
    manager, _oms = _make_pm()
    return manager


@pytest.fixture
def open_position_after_tp1(pm):
    """Long runner after TP1 booked on the tick path: tier==1, half size
    left, BE floor armed at entry."""
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    pos = pm._oms.submit(sig, 4.0)
    remaining = pm.manage_tick_exit(pos, tick_price=120.0, tick_time="12:00:00")
    assert remaining is not None and remaining.size == 2   # tier==1 state ready
    return remaining


def test_runner_not_killed_at_sig_tp_on_tick_path(pm, open_position_after_tp1):
    pos = open_position_after_tp1           # tier==1, half booked, BE armed
    out = pm.manage_tick_exit(pos, tick_price=120.05, tick_time="12:01:00")
    assert out is not None                  # runner STILL ALIVE at sig_tp touch


def test_runner_closes_at_tp2_on_tick_path(pm, open_position_after_tp1):
    pos = open_position_after_tp1
    entry = float(pos.order.signal.entry)
    long = pos.size > 0
    tp2 = entry + 2.0 * (float(pos.order.signal.tp) - entry) if long else \
          entry - 2.0 * (entry - float(pos.order.signal.tp))
    out = pm.manage_tick_exit(pos, tick_price=tp2, tick_time="12:02:00")
    assert out is None                      # runner closes at the real TP2


def test_be_floor_hit_journals_breakeven_not_sl(pm, open_position_after_tp1):
    """A stop touched purely via the armed BE floor must journal as
    BREAKEVEN (scratch), not SL — bar-path parity with exit_checks Rule 4b."""
    pos = open_position_after_tp1           # tier==1 runner, BE floor armed at entry
    out = pm.manage_tick_exit(
        pos,
        tick_price=float(pos.order.signal.entry) - 0.05,
        tick_time="12:03:00",
    )
    assert out is None                                  # closed
    assert pm.last_fill is not None and pm.last_fill.reason == "BREAKEVEN"
