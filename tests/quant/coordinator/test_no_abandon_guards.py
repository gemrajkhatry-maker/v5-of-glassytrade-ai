# tests/quant/coordinator/test_no_abandon_guards.py
"""Phase 5: rotation/rescan/switch must never abandon an open book.

Regression: QuantEngine never defined the ``engine._position`` attribute the
rotation/migration guards consulted, so on REAL engines every guard read None
— dead/drifted contracts could be rotated/migrated/switched away WHILE
holding a live position. The stopped engine's book sat at the broker with no
manager, and once the engine left the coordinator map the EOD square-off
backstop could no longer see it either (overnight orphan).

These tests drive REAL QuantEngine objects (with real folded EngineState +
PositionManager) through the coordinator guards.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from quant.brokers.gateway import Tick
from quant.decision.signal_builder import Signal
from quant.multi_engine import QuantCoordinator
from quant.runtime import QuantEngine
from quant.transitions import _position_to_state
from tests.helpers.synthetic import SyntheticGateway


def _make_real_engine(symbol: str) -> QuantEngine:
    return QuantEngine(
        SyntheticGateway([Tick("t0", 100.0, 10, 5, 5)]),
        symbol,
        interval_seconds=1,
        market="NSE",
    )


def _open_position_on(eng: QuantEngine):
    sig = Signal(
        type="LONG", reason="test", entry=100.0, sl=90.0, tp=120.0,
        rr=2.0, model_label="Triple-A", symbol=eng.symbol, timestamp="t",
    )
    pos = eng._oms.submit(sig, 1.0)
    eng.state = eng.state.with_position(_position_to_state(pos))
    eng._get_position_manager().current_position = pos


def _coord_with(engines: dict) -> QuantCoordinator:
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._engines = engines
    coord.config = {}
    return coord


def test_switch_symbol_refuses_when_old_engine_holds_position():
    """Switching away from a contract with an open book is refused — the old
    engine keeps running (position stays managed), nothing is abandoned."""
    old_sym = "NIFTY 1 SEP 25000 CALL"
    eng = _make_real_engine(old_sym)
    _open_position_on(eng)
    coord = _coord_with({old_sym: eng})
    coord._feed = MagicMock()
    coord._spawn_engine = MagicMock()

    ok = coord.switch_symbol(old_sym, "NIFTY 1 SEP 25100 CALL")

    assert ok is False, "switch must be refused while a position is open"
    assert old_sym in coord._engines, "the old engine must keep trading"
    coord._spawn_engine.assert_not_called()


def test_switch_symbol_allows_when_flat():
    """A flat contract may be switched as before."""
    old_sym = "NIFTY 1 SEP 25000 CALL"
    eng = _make_real_engine(old_sym)  # flat: fresh engine, no injected position
    coord = _coord_with({old_sym: eng})
    coord._feed = MagicMock()
    coord._spawn_engine = MagicMock()
    coord._contracts_file = "/tmp/none.json"
    coord._stop_engine = MagicMock()

    ok = coord.switch_symbol(old_sym, "NIFTY 1 SEP 25100 CALL")

    assert ok is True
    coord._stop_engine.assert_called_once_with(old_sym)


@patch("quant.multi_engine.is_trading_day", return_value=True)
def test_rescan_refuses_while_any_engine_holds_position(mock_day):
    """rescan() must not stop every engine while one holds an open book."""
    held_sym = "NIFTY 1 SEP 25000 CALL"
    eng = _make_real_engine(held_sym)
    _open_position_on(eng)
    flat_eng = _make_real_engine("NIFTY SEP FUT")
    coord = _coord_with({held_sym: eng, "NIFTY SEP FUT": flat_eng})
    coord._stop_engines = MagicMock()
    coord._feed = MagicMock()

    symbols = coord.rescan()

    assert symbols == [], "rescan must be refused with an open book"
    coord._stop_engines.assert_not_called()
    assert held_sym in coord._engines


@patch("quant.multi_engine.is_trading_day", return_value=True)
def test_rescan_proceeds_when_all_flat(mock_day):
    """Fully-flat book: rescan behaves as before."""
    coord = _coord_with({"NIFTY SEP FUT": _make_real_engine("NIFTY SEP FUT")})
    coord._stop_engines = MagicMock()
    coord._feed = MagicMock()
    coord._scan = MagicMock(return_value=["NIFTY SEP FUT", "NIFTY 1 SEP 25000 CALL"])
    coord._refresh_gex = MagicMock()
    coord._spawn_engine = MagicMock()
    coord._start_eod_watchdog = MagicMock()

    symbols = coord.rescan()

    assert symbols == ["NIFTY SEP FUT", "NIFTY 1 SEP 25000 CALL"]
    coord._stop_engines.assert_called_once()


def test_migrate_drift_check_does_not_crash_on_real_engines():
    """Regression: check_and_migrate_drifted_strikes read ``engine._position``
    (never defined on QuantEngine) — a real engine raised AttributeError. With
    the real position authority it runs cleanly on real (flat) engines."""
    coord = _coord_with({
        "NIFTY SEP FUT": _make_real_engine("NIFTY SEP FUT"),
        "NIFTY 1 SEP 25000 CALL": _make_real_engine("NIFTY 1 SEP 25000 CALL"),
    })
    # No usable spot source: get_quote must FAIL (MagicMock's __float__ would
    # otherwise report a phantom spot of 1.0 and every strike looks drifted).
    coord.market_data = MagicMock()
    coord.market_data.get_quote.side_effect = RuntimeError("no live feed")
    coord.rescan = MagicMock()

    drifted = coord.check_and_migrate_drifted_strikes(max_drift_steps=2.5)

    assert drifted == []  # no crash; no spot source -> nothing drifted
    coord.rescan.assert_not_called()


def test_rotate_guard_skips_real_engine_with_open_position():
    """A REAL engine holding an open position is never rotated — the exact
    scenario the phantom-attribute check let through."""
    held_sym = "NIFTY 1 SEP 25000 CALL"
    eng = _make_real_engine(held_sym)
    _open_position_on(eng)
    coord = _coord_with({held_sym: eng})
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE"}

    rotated = coord.check_and_rotate_dead_symbols()

    assert rotated == []
    assert held_sym in coord._engines