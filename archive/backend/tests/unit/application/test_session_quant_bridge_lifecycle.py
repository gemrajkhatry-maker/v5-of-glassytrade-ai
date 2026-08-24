from __future__ import annotations

from unittest.mock import Mock

from app.application.services.quant_bridge import QuantBridge
from app.application.services.session_state_manager import SessionState, SessionStateManager


def test_session_day_initialization_is_not_a_rollover() -> None:
    manager = SessionStateManager(storage=None)
    session = SessionState(symbol="SYM")

    assert manager._maybe_reset_symbol_state(session, "SYM", "2026-08-07T09:15:00+05:30") is False
    assert session._playbook_guard_day == "2026-08-07"
    assert session._explainability_day == "2026-08-07"


def test_same_session_day_does_not_reset_state() -> None:
    manager = SessionStateManager(storage=None)
    session = SessionState(
        symbol="SYM",
        _playbook_guard_day="2026-08-07",
        _explainability_day="2026-08-07",
    )
    manager._reset_playbook_guard_state = Mock()
    manager._reset_explainability_state = Mock()

    assert manager._maybe_reset_symbol_state(session, "SYM", "2026-08-07T10:00:00+05:30") is False
    manager._reset_playbook_guard_state.assert_not_called()
    manager._reset_explainability_state.assert_not_called()


def test_session_day_rollover_signals_reset() -> None:
    manager = SessionStateManager(storage=None)
    session = SessionState(
        symbol="SYM",
        _playbook_guard_day="2026-08-07",
        _explainability_day="2026-08-07",
    )
    manager._reset_playbook_guard_state = Mock()
    manager._reset_explainability_state = Mock()

    assert manager._maybe_reset_symbol_state(session, "SYM", "2026-08-08T09:15:00+05:30") is True
    assert session._playbook_guard_day == "2026-08-08"
    assert session._explainability_day == "2026-08-08"
    manager._reset_playbook_guard_state.assert_called_once_with(session, "SYM")
    manager._reset_explainability_state.assert_called_once_with(session)


def test_partial_marker_for_current_day_does_not_reset() -> None:
    manager = SessionStateManager(storage=None)
    session = SessionState(
        symbol="SYM",
        _playbook_guard_day="2026-08-07",
        _explainability_day="",
    )
    manager._reset_playbook_guard_state = Mock()
    manager._reset_explainability_state = Mock()

    assert manager._maybe_reset_symbol_state(session, "SYM", "2026-08-07T11:00:00+05:30") is False
    manager._reset_playbook_guard_state.assert_not_called()
    manager._reset_explainability_state.assert_not_called()


def test_stale_primary_marker_with_missing_secondary_marker_is_rollover() -> None:
    manager = SessionStateManager(storage=None)
    session = SessionState(
        symbol="SYM",
        _playbook_guard_day="2026-08-06",
        _explainability_day="",
    )
    manager._reset_playbook_guard_state = Mock()
    manager._reset_explainability_state = Mock()

    assert manager._maybe_reset_symbol_state(session, "SYM", "2026-08-07T11:00:00+05:30") is True
    manager._reset_playbook_guard_state.assert_called_once_with(session, "SYM")
    manager._reset_explainability_state.assert_called_once_with(session)


def test_quant_bridge_reset_allows_reprocessing_same_bar() -> None:
    bridge = QuantBridge()
    bar = type(
        "OHLCStub",
        (),
        {
            "time": "2026-08-07T09:15:00+05:30",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 100.0,
            "taker_buy_volume": 60.0,
            "delta": 20.0,
        },
    )()

    bridge.on_bar_close("SYM", bar)
    assert bridge.on_bar_close("SYM", bar) == {}
    bridge.reset("SYM")
    assert bridge.on_bar_close("SYM", bar) != {}
