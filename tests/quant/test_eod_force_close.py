"""D-3: a pyramid-only force-close must not bypass the single release path.

Review follow-ups (money path):

* a pyramid-only flatten is bookkeeping, not a new round-trip — it must not
  consume ``trades_today`` (which feeds ``SessionRisk.can_trade``) or move the
  consecutive win/loss streaks the halt is built on;
* the double-close guard returns ``None`` (no fill) and the helper must not
  read ``pm.last_fill.pnl`` blind;
* one bad add-on must not orphan the rest.
"""

import pytest

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Order, Position
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager


def _pyramid(level: int = 1, size: float = 10.0, entry: float = 100.0, _id=None):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=99.0, tp=103.0,
                 rr=3.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    kwargs = {} if _id is None else {"_id": _id}
    return Position(order=Order(sig, size), open_price=entry, open_time="t0",
                    size=size, pyramid_level=level, is_pyramid=True, **kwargs)


class _SpiedPortfolioRisk(PortfolioRiskAuthority):
    """Captures record_close so the release, not just the list, is asserted."""

    def __init__(self):
        super().__init__()
        self.realized_calls: list[tuple[float, float]] = []

    def record_close(self, risk_rupees, pnl, symbol="", is_full_close=False):
        self.realized_calls.append((float(risk_rupees), float(pnl)))
        super().record_close(risk_rupees, pnl, symbol=symbol,
                             is_full_close=is_full_close)


def _make_pm(portfolio_risk=None, **risk_kwargs):
    return PositionManager(
        oms=PaperOMS(lot_size=1.0),
        exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="SYM", **risk_kwargs),
        emit_fn=lambda e: None,
        symbol="SYM",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        portfolio_risk=portfolio_risk,
    )


def test_pyramid_only_close_stamps_exit_source():
    """A lingering pyramid add-on must be closed through _execute_full_close,
    so last_exit_source is stamped and the close is logged like any other."""
    events = []
    pm = _make_pm()
    pm._emit = events.append
    pm.pyramid_positions = [_pyramid()]
    pm.current_position = None

    # The runtime helper under test (extracted so it is callable in isolation).
    from quant.runtime import close_lingering_pyramids

    bar = Bar("2026-09-10T15:20:00", 100.0, 101.0, 99.0, 100.0, 10, 10)
    closed = close_lingering_pyramids(pm, 100.0, bar.time, "EOD_SQUARE_OFF")

    assert closed == 1
    assert pm.pyramid_positions == []
    # The stamp is the whole point: previously this path left it blank/stale.
    assert pm._exits.last_exit_source == "DETERMINISTIC:EOD_SQUARE_OFF"
    assert any(type(e).__name__ == "PositionClosed" for e in events)


def test_pyramid_only_close_does_not_count_as_trade():
    """A pyramid-only flatten must not consume the session trade budget.

    Regression: routing the add-ons through _execute_full_close ran
    ``record_trade(fill.pnl)`` with the default ``count_as_trade=True``, so
    closing 3 add-ons at a loss set trades_today=3 and tripped the halt — even
    though eod_square_off promises it does not persist a risk halt.
    """
    pm = _make_pm()
    before = pm._risk.state()
    assert before.trades_today == 0

    pm.pyramid_positions = [
        _pyramid(level=1, size=10.0, _id="pyr-1"),
        _pyramid(level=2, size=8.0, _id="pyr-2"),
        _pyramid(level=3, size=6.0, _id="pyr-3"),
    ]
    pm.current_position = None

    from quant.runtime import close_lingering_pyramids

    closed = close_lingering_pyramids(pm, 98.0, "2026-09-10T15:20:00", "EOD_SQUARE_OFF")

    assert closed == 3, "all three add-ons must close"
    after = pm._risk.state()
    assert after.trades_today == before.trades_today == 0, (
        "a pyramid-only flatten must not consume the session trade budget"
    )
    assert after.consecutive_losses == 0, "losses must not move the halt streak"
    assert after.daily_pnl < 0.0, "the realized P&L must still be booked"


def test_pyramid_only_close_releases_risk_per_add_on():
    """>1 add-on: each close must release its own reserved aggregate risk."""
    spied = _SpiedPortfolioRisk()
    pm = _make_pm(portfolio_risk=spied)
    pm.pyramid_positions = [
        _pyramid(level=1, size=2.0, entry=100.5, _id="pyr-1"),
        _pyramid(level=2, size=1.0, entry=101.0, _id="pyr-2"),
    ]
    pm._pyramid_open_risk = {"pyr-1": 0.6, "pyr-2": 1.0}
    pm.current_position = None

    from quant.runtime import close_lingering_pyramids

    closed = close_lingering_pyramids(pm, 103.0, "t3", "EOD_SQUARE_OFF")

    assert closed == 2
    assert pm.pyramid_positions == []
    assert pm._pyramid_open_risk == {}, "reserved risk must not leak"
    assert len(spied.realized_calls) == 2
    assert sorted(r for r, _ in spied.realized_calls) == [0.6, 1.0]
    assert sorted(p for _, p in spied.realized_calls) == pytest.approx([2.0, 5.0])


def test_pyramid_only_close_survives_double_close_guard():
    """An add-on already in _closed_ids returns None (no fill) from
    _execute_full_close. The helper must not read last_fill.pnl blind."""
    spied = _SpiedPortfolioRisk()
    pm = _make_pm(portfolio_risk=spied)
    pm.pyramid_positions = [_pyramid(_id="already-closed")]
    pm._pyramid_open_risk = {"already-closed": 0.5}
    pm._closed_ids.add("already-closed")
    pm.current_position = None

    from quant.runtime import close_lingering_pyramids

    closed = close_lingering_pyramids(pm, 98.0, "t4", "EOD_SQUARE_OFF")

    assert closed == 0
    assert spied.realized_calls == [], "no fill means no risk release"
    assert pm._pyramid_open_risk == {"already-closed": 0.5}, "risk stays reserved"


def test_guarded_skip_keeps_addon_in_book_for_retry():
    """A guarded skip is a FAILED close, not a successful one (D-15).

    ``_closed_ids`` now lives for the manager lifetime, so an id collision
    (e.g. a reused/replayed id) is reachable. The skip means nothing executed
    at the broker, so the add-on may still be live: dropping it from the book
    would orphan a real position with no retry. It must stay in the book.
    """
    pm = _make_pm()
    addon = _pyramid(_id="dup-1")
    pm.pyramid_positions = [addon]
    pm._closed_ids.add("dup-1")
    pm.current_position = None

    from quant.runtime import close_lingering_pyramids

    closed = close_lingering_pyramids(pm, 98.0, "t", "EOD_SQUARE_OFF")

    assert closed == 0, "a guarded skip closed nothing"
    assert [p._id for p in pm.pyramid_positions] == ["dup-1"], (
        "the add-on may still be open at the broker, so it must stay in the book"
    )
    assert pm.pyramid_count == 1, "book count must match pyramid_positions"


def test_pyramid_only_close_one_failure_does_not_orphan_the_rest():
    """One raising add-on must not strand the add-ons behind it."""
    pm = _make_pm()
    good_a = _pyramid(_id="good-a")
    bad = _pyramid(_id="bad")
    good_b = _pyramid(_id="good-b")
    pm.pyramid_positions = [good_a, bad, good_b]
    pm.current_position = None

    real_close = pm._execute_full_close

    def flaky(position, *args, **kwargs):
        if getattr(position, "_id", None) == "bad":
            raise RuntimeError("oms boom")
        return real_close(position, *args, **kwargs)

    pm._execute_full_close = flaky

    from quant.runtime import close_lingering_pyramids

    closed = close_lingering_pyramids(pm, 100.0, "t5", "EOD_SQUARE_OFF")

    assert closed == 2, "the two healthy add-ons must still close"
    assert [p._id for p in pm.pyramid_positions] == ["bad"], (
        "the failed add-on stays in the book for a retry"
    )
    assert pm.pyramid_count == 1
