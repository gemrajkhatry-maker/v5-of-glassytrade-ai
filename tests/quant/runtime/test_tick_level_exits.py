# tests/quant/runtime/test_tick_level_exits.py
import pytest
from quant.brokers.gateway import Tick
from quant.events import PositionClosed
from quant.decision.signal_builder import Signal
from quant.execution.exit_checks import tp2_level
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


def test_tick_tp_second_touch_books_final_partial_keeps_runner():
    """After TP1 books the half, a TP2 tag books the FINAL half of what
    remains (quarter runner survives) — strict bar parity with Rule 4,
    where tiers stop at 2 and the runner dies only via trail/BE/drift/TIME.
    (This test codified full-close-at-TP2 before wave 3 fixed the
    divergence; it now asserts the survive-with-tier-2 contract.)"""
    pm, oms = _make_pm()
    sig = _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0)
    open_position = oms.submit(sig, 4.0)

    remaining = pm.manage_tick_exit(open_position, tick_price=120.0, tick_time="12:00:00")
    assert remaining is not None and remaining.size == 2

    out = pm.manage_tick_exit(remaining, tick_price=140.0, tick_time="12:00:01")
    assert out is not None                       # quarter runner survives TP2
    assert out.size == pytest.approx(1.0)        # halved again (50%-of-remainder)
    assert pm.last_partial_fill is not None
    assert pm.last_partial_fill.reason == "TP2"
    assert pm.last_fill is None                  # NOT a full close
    assert pm._exits._tp_tier[out._id] == 2      # final tier armed


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


def test_runner_books_final_partial_at_tp2_on_tick_path(pm, open_position_after_tp1):
    """Runner (tier==1) at a TP2 tag books the final partial, arms tier=2 and
    survives — same lifecycle as bar-path Rule 4 (tiers stop at 2).
    Previously this test asserted full-close-at-TP2; that codified the
    divergence fixed in wave 3."""
    pos = open_position_after_tp1
    tp2 = tp2_level(float(pos.order.signal.entry), float(pos.order.signal.tp))
    out = pm.manage_tick_exit(pos, tick_price=tp2, tick_time="12:02:00")
    assert out is not None                       # quarter runner survives
    assert out.size == pytest.approx(1.0)        # 2 -> 1 (50%-of-remainder)
    assert pm._exits._tp_tier[pos._id] == 2      # final tier armed
    assert pm.last_partial_fill is not None and pm.last_partial_fill.reason == "TP2"
    assert pm.last_fill is None                  # NOT a full close


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


# ---------------------------------------------------------------------------
# Short-side mirror of the runner TP geometry + BREAKEVEN journaling above.
# Each short test below flips ONLY the signal side vs its long mirror; the
# price magnitudes are identical (entry=100, tp=80 mirrors tp=120 around
# entry), so any behavioural divergence is direction logic, not thresholds.
# ---------------------------------------------------------------------------

@pytest.fixture
def open_short_position_after_tp1(pm):
    """Short runner after TP1 booked on the tick path: tier==1, half size
    left, BE floor armed at entry (mirror of open_position_after_tp1)."""
    sig = _make_signal(symbol="TEST", side="SHORT", entry=100.0, sl=110.0, tp=80.0)
    pos = pm._oms.submit(sig, 4.0)
    remaining = pm.manage_tick_exit(pos, tick_price=80.0, tick_time="12:00:00")
    assert remaining is not None and remaining.size == -2   # tier==1 state ready
    return remaining


def test_short_runner_not_killed_at_sig_tp_on_tick_path(pm, open_short_position_after_tp1):
    pos = open_short_position_after_tp1     # tier==1, half booked, BE armed
    # Mirror of the long test's sig_tp+0.05 nudge past the tag; on a short a
    # sig_tp touch means trading BELOW tp (=80), so we probe 79.95.
    out = pm.manage_tick_exit(pos, tick_price=79.95, tick_time="12:01:00")
    assert out is not None                  # runner STILL ALIVE at sig_tp touch


def test_short_runner_books_final_partial_at_tp2_on_tick_path(pm, open_short_position_after_tp1):
    """Short mirror: a TP2 tag books the final partial and the runner
    survives at tier==2 (mirror of the long Rule-4 lifecycle).
    Previously asserted full-close-at-TP2 — that codified the divergence
    fixed in wave 3."""
    pos = open_short_position_after_tp1
    entry = float(pos.order.signal.entry)
    tp2 = tp2_level(entry, float(pos.order.signal.tp))
    assert tp2 == pytest.approx(entry - 2.0 * abs(80.0 - 100.0))  # = 60.0
    out = pm.manage_tick_exit(pos, tick_price=tp2, tick_time="12:02:00")
    assert out is not None                       # quarter runner survives
    assert out.size == pytest.approx(-1.0)       # -2 -> -1 (50%-of-remainder)
    assert pm._exits._tp_tier[pos._id] == 2      # final tier armed
    assert pm.last_partial_fill is not None and pm.last_partial_fill.reason == "TP2"
    assert pm.last_fill is None                  # NOT a full close


def test_short_be_floor_hit_journals_breakeven_not_sl(pm, open_short_position_after_tp1):
    """A short stop touched purely via the armed BE floor must journal as
    BREAKEVEN (scratch), not SL — mirror of the long Rule 4b path."""
    pos = open_short_position_after_tp1     # tier==1 runner, BE floor armed at entry
    # Mirror of the long test's entry−0.05 breach; on a short a BE-floor hit
    # means trading ABOVE entry, so we probe entry+0.05 with the same delta.
    out = pm.manage_tick_exit(
        pos,
        tick_price=float(pos.order.signal.entry) + 0.05,
        tick_time="12:03:00",
    )
    assert out is None                                  # closed
    assert pm.last_fill is not None and pm.last_fill.reason == "BREAKEVEN"


# ---------------------------------------------------------------------------
# Wave 3 — strict bar/tick parity for the FINAL tier: a TP2 touch books the
# last partial (tier -> 2, runner alive); thereafter no tick-level profit
# exits exist at all (runner dies only via trail/BE/drift/TIME/session or the
# bar path).
# ---------------------------------------------------------------------------

def _beyond(level: float, pos) -> float:
    """First tick strictly beyond `level` in the position's profit direction."""
    return level + (0.05 if pos.size > 0 else -0.05)


@pytest.fixture
def pm_after_tp2(pm, open_position_after_tp1):
    """Long runner parked at tier==2 after the TP2 partial booked."""
    pos = open_position_after_tp1
    pre_size = abs(pos.size)
    tp2 = tp2_level(float(pos.order.signal.entry), float(pos.order.signal.tp))
    remaining = pm.manage_tick_exit(pos, tick_price=_beyond(tp2, pos), tick_time="12:02:00")
    assert remaining is not None and abs(remaining.size) * 2 <= pre_size
    return remaining


@pytest.fixture
def short_pm_after_tp2(pm, open_short_position_after_tp1):
    """Short mirror of pm_after_tp2: runner parked at tier==2."""
    pos = open_short_position_after_tp1
    pre_size = abs(pos.size)
    tp2 = tp2_level(float(pos.order.signal.entry), float(pos.order.signal.tp))
    remaining = pm.manage_tick_exit(pos, tick_price=_beyond(tp2, pos), tick_time="12:02:00")
    assert remaining is not None and abs(remaining.size) * 2 <= pre_size
    return remaining


def test_tick_tp2_books_final_partial_not_full_close(pm, open_position_after_tp1):
    pos = open_position_after_tp1           # tier==1 runner alive (size 2)
    pre_size = abs(pos.size)
    tp2 = tp2_level(float(pos.order.signal.entry), float(pos.order.signal.tp))
    out = pm.manage_tick_exit(pos, tick_price=_beyond(tp2, pos), tick_time="12:02:00")
    assert out is not None                  # quarter runner survives
    assert abs(out.size) * 2 <= pre_size    # halved again
    assert pm._exits._tp_tier[pos._id] == 2
    assert pm.last_partial_fill is not None
    assert pm.last_partial_fill.reason == "TP2"
    assert out._id == pos._id               # same _id → tier state stays keyed


def test_runner_after_tp2_ignores_far_tp_ticks(pm, pm_after_tp2):
    """tier>=2 has NO tick-level TP semantics left: a deep profit tick must
    neither book anything nor close the runner (trail/BE/drift/TIME are the
    only remaining exits)."""
    pos = pm_after_tp2
    entry = float(pos.order.signal.entry)
    far = _beyond(tp2_level(entry, float(pos.order.signal.tp)) * 1.05, pos)
    out = pm.manage_tick_exit(pos, tick_price=far, tick_time="12:03:00")
    assert out is not None                  # no TP semantics left on ticks
    assert pm.last_fill is None             # nothing was closed


def test_short_tick_tp2_books_final_partial_not_full_close(pm, open_short_position_after_tp1):
    pos = open_short_position_after_tp1     # tier==1 short runner alive (size -2)
    pre_size = abs(pos.size)
    tp2 = tp2_level(float(pos.order.signal.entry), float(pos.order.signal.tp))
    out = pm.manage_tick_exit(pos, tick_price=_beyond(tp2, pos), tick_time="12:02:00")
    assert out is not None                  # quarter runner survives
    assert abs(out.size) * 2 <= pre_size    # halved again
    assert pm._exits._tp_tier[pos._id] == 2
    assert pm.last_partial_fill is not None
    assert pm.last_partial_fill.reason == "TP2"


def test_short_runner_after_tp2_ignores_far_tp_ticks(pm, short_pm_after_tp2):
    """Short mirror: at tier>=2, a far profit tick keeps the runner alive."""
    pos = short_pm_after_tp2
    entry = float(pos.order.signal.entry)
    far = _beyond(tp2_level(entry, float(pos.order.signal.tp)) * 1.05, pos)
    out = pm.manage_tick_exit(pos, tick_price=far, tick_time="12:03:00")
    assert out is not None                  # no TP semantics left on ticks
    assert pm.last_fill is None             # nothing was closed
