from quant.execution.protective_stop import ProtectiveStopState


def test_long_stop_tightens_monotonically():
    state = ProtectiveStopState(submitted_sl=95.0)
    state = state.tighten(99.0, kind="TRAIL", bar_index=1)
    state = state.tighten(98.0, kind="TRAIL", bar_index=2)
    assert state.trail_stop == 99.0
    assert state.effective_stop == 99.0


def test_short_stop_tightens_monotonically():
    state = ProtectiveStopState(submitted_sl=105.0, side="SHORT")
    state = state.tighten(101.0, kind="TRAIL", bar_index=1)
    state = state.tighten(102.0, kind="TRAIL", bar_index=2)
    assert state.trail_stop == 101.0
    assert state.effective_stop == 101.0


def test_breakeven_and_trail_use_tightest_protective_level():
    state = ProtectiveStopState(submitted_sl=95.0)
    state = state.tighten(100.0, kind="BREAKEVEN", bar_index=1)
    state = state.tighten(101.0, kind="TRAIL", bar_index=2)
    assert state.breakeven_floor == 100.0
    assert state.trail_stop == 101.0
    assert state.effective_stop == 101.0


def test_invalid_or_non_tightening_candidates_are_ignored():
    state = ProtectiveStopState(submitted_sl=95.0)
    assert state.tighten(0.0, kind="TRAIL", bar_index=1) == state
    assert state.tighten(94.0, kind="TRAIL", bar_index=2) == state

from quant.execution.protective_stop import resolve_protective_stop


def test_resolve_protective_stop_matches_bar_and_tick_precedence():
    assert resolve_protective_stop(95.0, 100.0, 99.0, "LONG") == (100.0, "BREAKEVEN")
    assert resolve_protective_stop(105.0, 100.0, 101.0, "SHORT") == (100.0, "BREAKEVEN")
    assert resolve_protective_stop(95.0, None, 99.0, "LONG") == (99.0, "TRAIL")
    assert resolve_protective_stop(95.0, 99.0, 99.0, "LONG") == (99.0, "TRAIL")
