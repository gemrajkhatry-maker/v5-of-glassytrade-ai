# tests/quant/runtime/test_tick_partial_adoption.py
"""Regression: the ENGINE must adopt the surviving Position returned by a
tick-path tiered partial (manage_tick_exit -> _tick_tp_touch).

Lane A traced the paper harness double-booking here: an intrabar TP1 touch
booked half, but the engine kept holding the pre-partial Position — the later
full close re-booked the ORIGINAL size (2000 closed vs 1000 opened). These
tests drive QuantEngine through SyntheticGateway ticks (not the PM directly)
and assert inventory conservation plus fractional reserve release.
"""
import pytest

from quant.brokers.gateway import Tick
from quant.decision.signal_builder import Signal
from quant.events import PositionClosed, PositionReduced
from quant.execution.portfolio_risk import PortfolioRiskAuthority
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


_BASE = 1700000000


def _intraday_ticks():
    """Entry-area tick -> intrabar TP touch (books tick-path TP1 partial) ->
    runner-alive probe -> stop-side breach that must fully close ONLY the
    adopted remainder. All epochs stay inside ONE aggregator window so no bar
    (and no session force-exit) interferes: every exit below is tick-path."""
    return [
        Tick(str(_BASE), 100.0, 10, 5, 5),
        Tick(str(_BASE + 30), 121.0, 10, 10, 0),
        Tick(str(_BASE + 60), 121.05, 10, 10, 0),
        Tick(str(_BASE + 90), 89.0, 10, 0, 10),
    ]


_OPENED_SIZE = 4.0


def _make_engine(ticks, **kw):
    gw = SyntheticGateway(ticks)
    return QuantEngine(gw, "TEST", interval_seconds=300, **kw)


def _open_long(eng):
    # Same injection pattern as tests/quant/runtime/test_tick_level_exits.py
    sig = _make_signal()
    eng._position = eng._oms.submit(sig, _OPENED_SIZE)
    eng._entry_bar_index = 0
    return eng._position


def _fills(eng):
    """All exit fills (partials are reductions, not closes)."""
    return [
        e.fill
        for e in eng.events
        if isinstance(e, (PositionClosed, PositionReduced))
    ]


def test_engine_adopts_tick_partial_remainder_inventory_conserved():
    """Tick-path TP1 partial -> engine manages the REDUCED survivor: exactly
    one partial fires, one full close fires, closed sizes sum to the opened
    size exactly once (inventory conservation)."""
    eng = _make_engine(_intraday_ticks())
    opened = _open_long(eng)

    eng.run()

    reduced = [e for e in eng.events if isinstance(e, PositionReduced)]
    closed = [e for e in eng.events if isinstance(e, PositionClosed)]

    assert abs(opened.size) == _OPENED_SIZE
    # one TP1 partial on the tick path, nothing else books a partial
    assert len(reduced) == 1, (
        f"expected exactly 1 partial, got {[(f.reason, f.position.size) for f in _fills(eng)]}"
    )
    assert reduced[0].fill.reason == "TP1"
    assert reduced[0].fill.position.size == pytest.approx(2.0)
    assert reduced[0].remaining is not None
    assert reduced[0].remaining.size == pytest.approx(2.0)
    # full close books ONLY the adopted remainder — not the original size
    assert len(closed) == 1
    assert closed[0].fill.position.size == pytest.approx(2.0)
    assert eng._position is None

    total_closed = sum(abs(f.position.size) for f in _fills(eng))
    assert total_closed == pytest.approx(_OPENED_SIZE), (
        f"inventory double-booked: closed {total_closed} vs opened {_OPENED_SIZE}"
    )
    ids = {f.position.open_time for f in _fills(eng)}
    assert ids == {opened.open_time}


def test_tick_partial_releases_portfolio_reserves_fractionally():
    """Same lifecycle with a live PortfolioRiskAuthority seeded the way the
    engine's entry path seeds it: the TP1 partial releases the closed fraction
    (2/4) of reserved open risk, the full close releases the rest; partial
    PnL must be recorded exactly once per fill."""
    auth = PortfolioRiskAuthority(starting_equity=1_000_000)
    eng = _make_engine(_intraday_ticks(), portfolio_risk=auth)
    _open_long(eng)
    # mimic the entry path's reserve registration (entry-sl)*qty = (100-90)*4
    entry_risk = 400.0
    assert auth.register_open(entry_risk)
    eng._open_trade_risk = entry_risk

    eng.run()

    # partial released 2/4 * 400 = 200; full close released the remaining 200
    assert auth.open_risk == pytest.approx(0.0)
    # TP1 pnl (121-100)*2 = 42 recorded once + BREAKEVEN close (89-100)*2 = -22
    assert auth.realized_pnl == pytest.approx(20.0), (
        f"expected 42 + (-22), got {auth.realized_pnl} "
        "(a stale partial-fill re-release or missing fill would break this)"
    )
