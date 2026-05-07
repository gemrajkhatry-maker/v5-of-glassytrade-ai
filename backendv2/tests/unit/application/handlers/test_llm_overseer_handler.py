"""Tests for llm_overseer_handler.py — should_run, run_overseer, _resolve_placeholder."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.llm_overseer_handler import (
    LLMOverseerHandler,
    OVERSEER_COOLDOWN,
)


class TestShouldRun:
    """Tests for should_run() — position, readiness, cooldown checks."""

    def _make_handler(self, gen_ai_service=None, trade_manager=None):
        return LLMOverseerHandler(gen_ai_service=gen_ai_service, trade_manager=trade_manager)

    def test_no_position_returns_false(self):
        """When has_position is False, overseer should not run."""
        handler = self._make_handler()
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=False,
            ai_running=False,
            has_position=False,
        )
        assert result is False

    def test_overseer_already_running_returns_false(self):
        """When overseer_running is True, overseer should not run."""
        handler = self._make_handler()
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=True,
            ai_running=False,
            has_position=True,
        )
        assert result is False

    def test_ai_already_running_returns_false(self):
        """When ai_running is True, overseer should not run."""
        handler = self._make_handler()
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=False,
            ai_running=True,
            has_position=True,
        )
        assert result is False

    def test_gen_ai_not_ready_returns_false(self):
        """When gen_ai_service.is_ready() returns False, overseer should not run."""
        gen_ai_service = MagicMock()
        gen_ai_service.is_ready.return_value = False
        handler = self._make_handler(gen_ai_service=gen_ai_service)
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=False,
            ai_running=False,
            has_position=True,
        )
        assert result is False

    def test_gen_ai_ready_allows_run(self):
        """When gen_ai_service.is_ready() returns True, cooldown check proceeds."""
        gen_ai_service = MagicMock()
        gen_ai_service.is_ready.return_value = True
        handler = self._make_handler(gen_ai_service=gen_ai_service)
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=False,
            ai_running=False,
            has_position=True,
        )
        assert result is True

    def test_gen_ai_without_is_ready_skips_readiness(self):
        """When gen_ai_service has no is_ready attribute, readiness check is skipped."""
        gen_ai_service = MagicMock(spec=["some_other_method"])
        handler = self._make_handler(gen_ai_service=gen_ai_service)
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=False,
            ai_running=False,
            has_position=True,
        )
        assert result is True

    def test_gen_ai_service_is_none_skips_readiness(self):
        """When gen_ai_service is None, readiness check is skipped."""
        handler = self._make_handler(gen_ai_service=None)
        result = handler.should_run(
            last_overseer_time=0.0,
            overseer_running=False,
            ai_running=False,
            has_position=True,
        )
        assert result is True

    def test_cooldown_not_elapsed_returns_false(self):
        """When cooldown has not elapsed, overseer should not run."""
        handler = self._make_handler()
        with patch("app.application.handlers.llm_overseer_handler.time") as mock_time:
            mock_time.time.return_value = 100.0
            result = handler.should_run(
                last_overseer_time=98.0,  # only 2 seconds ago, cooldown is 3.0
                overseer_running=False,
                ai_running=False,
                has_position=True,
            )
        assert result is False

    def test_cooldown_elapsed_returns_true(self):
        """When cooldown has elapsed, overseer should run."""
        handler = self._make_handler()
        with patch("app.application.handlers.llm_overseer_handler.time") as mock_time:
            mock_time.time.return_value = 100.0
            result = handler.should_run(
                last_overseer_time=96.0,  # 4 seconds ago, cooldown is 3.0
                overseer_running=False,
                ai_running=False,
                has_position=True,
            )
        assert result is True

    def test_cooldown_at_exact_boundary_returns_true(self):
        """When time elapsed equals exactly OVERSEER_COOLDOWN, overseer should run."""
        handler = self._make_handler()
        with patch("app.application.handlers.llm_overseer_handler.time") as mock_time:
            mock_time.time.return_value = 100.0
            result = handler.should_run(
                last_overseer_time=100.0 - OVERSEER_COOLDOWN,
                overseer_running=False,
                ai_running=False,
                has_position=True,
            )
        assert result is True


class TestRunOverseer:
    """Tests for run_overseer() — flag setting, trade manager evaluation, error handling."""

    def _make_handler(self, gen_ai_service=None, trade_manager=None):
        return LLMOverseerHandler(gen_ai_service=gen_ai_service, trade_manager=trade_manager)

    def test_none_session_returns_early(self):
        """When session is None, run_overseer returns without side effects."""
        handler = self._make_handler()
        handler.run_overseer(None, "NIFTY", MagicMock())
        assert handler._last_run == {}

    def test_empty_symbol_returns_early(self):
        """When symbol is empty string, run_overseer returns without side effects."""
        handler = self._make_handler()
        handler.run_overseer(MagicMock(), "", MagicMock())
        assert handler._last_run == {}

    def test_sets_overseer_running_flag(self):
        """run_overseer sets session._overseer_running to True then False."""
        handler = self._make_handler()
        session = MagicMock()
        session._lock = MagicMock()
        session._lock.__enter__ = MagicMock(return_value=None)
        session._lock.__exit__ = MagicMock(return_value=None)
        session._open_positions = {}

        with patch("app.application.handlers.llm_overseer_handler.time") as mock_time:
            mock_time.time.return_value = 100.0
            handler.run_overseer(session, "NIFTY", MagicMock())

        assert session._overseer_running is False  # Ends as False after cleanup

    def test_updates_last_run_timestamp(self):
        """run_overseer updates _last_run dict with symbol key."""
        handler = self._make_handler()
        session = MagicMock()
        session._lock = MagicMock()
        session._lock.__enter__ = MagicMock(return_value=None)
        session._lock.__exit__ = MagicMock(return_value=None)
        session._open_positions = {}

        with patch("app.application.handlers.llm_overseer_handler.time") as mock_time:
            mock_time.time.return_value = 100.0
            handler.run_overseer(session, "BANKNIFTY", MagicMock())

        assert "BANKNIFTY" in handler._last_run
        assert handler._last_run["BANKNIFTY"] == 100.0

    def test_lock_error_on_entry_is_handled(self):
        """If acquiring the lock raises, entry-side error is handled gracefully."""
        handler = self._make_handler()
        session = MagicMock()
        session._lock = MagicMock()
        session._lock.__enter__ = MagicMock(side_effect=RuntimeError("lock failed"))
        session._open_positions = {}

        # Should not raise
        handler.run_overseer(session, "NIFTY", MagicMock())

    def test_lock_error_on_exit_is_handled(self):
        """If releasing the lock raises on exit, error is handled gracefully."""
        handler = self._make_handler()
        session = MagicMock()
        session._lock = MagicMock()
        call_count = [0]

        def fake_enter():
            call_count[0] += 1
            return None

        def fake_exit(*_):
            if call_count[0] == 1:
                return None  # First exit (entry block)
            raise RuntimeError("unlock failed")

        session._lock.__enter__ = MagicMock(side_effect=fake_enter)
        session._lock.__exit__ = MagicMock(side_effect=fake_exit)
        session._open_positions = {}

        # Should not raise
        handler.run_overseer(session, "NIFTY", MagicMock())

    def test_resolves_placeholder(self):
        """run_overseer calls _resolve_placeholder with session, symbol, tick."""
        handler = self._make_handler()
        session = MagicMock()
        session._lock = MagicMock()
        session._lock.__enter__ = MagicMock(return_value=None)
        session._lock.__exit__ = MagicMock(return_value=None)
        session._open_positions = {}
        tick = MagicMock()

        with patch.object(handler, "_resolve_placeholder") as mock_resolve:
            handler.run_overseer(session, "NIFTY", tick)
            mock_resolve.assert_called_once_with(session, "NIFTY", tick)


class TestResolvePlaceholder:
    """Tests for _resolve_placeholder() — delegation to trade manager."""

    def _make_handler(self, gen_ai_service=None, trade_manager=None):
        return LLMOverseerHandler(gen_ai_service=gen_ai_service, trade_manager=trade_manager)

    def test_no_open_positions_returns_early(self):
        """When session has no _open_positions, method returns without side effects."""
        handler = self._make_handler()
        session = MagicMock(spec=["_open_positions"])
        session._open_positions = None
        handler._resolve_placeholder(session, "NIFTY", MagicMock())
        # If we got here without error, the test passed

    def test_empty_open_positions_returns_early(self):
        """When _open_positions dict is empty, method returns without side effects."""
        handler = self._make_handler()
        session = MagicMock()
        session._open_positions = {}
        handler._resolve_placeholder(session, "NIFTY", MagicMock())

    def test_position_with_matching_symbol_is_evaluated(self):
        """When a position matches the symbol, trade_manager.evaluate is called."""
        trade_manager = MagicMock()
        handler = self._make_handler(trade_manager=trade_manager)

        position = MagicMock()
        position.symbol = "NIFTY"
        position.id = "pos-1"

        session = MagicMock()
        session._open_positions = {"pos-1": position}

        handler._resolve_placeholder(session, "NIFTY", MagicMock())
        trade_manager.evaluate.assert_called_once_with(position)

    def test_position_with_non_matching_symbol_is_skipped(self):
        """When position symbol does not match, trade_manager.evaluate is not called."""
        trade_manager = MagicMock()
        handler = self._make_handler(trade_manager=trade_manager)

        position = MagicMock()
        position.symbol = "BANKNIFTY"

        session = MagicMock()
        session._open_positions = {"pos-1": position}

        handler._resolve_placeholder(session, "NIFTY", MagicMock())
        trade_manager.evaluate.assert_not_called()

    def test_trade_manager_evaluate_error_is_handled(self):
        """If trade_manager.evaluate raises, error is caught and handled."""
        trade_manager = MagicMock()
        trade_manager.evaluate.side_effect = RuntimeError("evaluate failed")
        handler = self._make_handler(trade_manager=trade_manager)

        position = MagicMock()
        position.symbol = "NIFTY"
        position.id = "pos-1"

        session = MagicMock()
        session._open_positions = {"pos-1": position}

        # Should not raise
        handler._resolve_placeholder(session, "NIFTY", MagicMock())

    def test_no_trade_manager_skips_evaluation(self):
        """When trade_manager is None, evaluation is skipped."""
        handler = self._make_handler(trade_manager=None)

        position = MagicMock()
        position.symbol = "NIFTY"
        position.id = "pos-1"

        session = MagicMock()
        session._open_positions = {"pos-1": position}

        # Should not raise — no trade_manager to call
        handler._resolve_placeholder(session, "NIFTY", MagicMock())

    def test_multiple_positions_only_matching_evaluated(self):
        """When multiple positions exist, only the matching symbol is evaluated."""
        trade_manager = MagicMock()
        handler = self._make_handler(trade_manager=trade_manager)

        position1 = MagicMock()
        position1.symbol = "NIFTY"
        position1.id = "pos-1"

        position2 = MagicMock()
        position2.symbol = "BANKNIFTY"
        position2.id = "pos-2"

        session = MagicMock()
        session._open_positions = {"pos-1": position1, "pos-2": position2}

        handler._resolve_placeholder(session, "NIFTY", MagicMock())
        trade_manager.evaluate.assert_called_once_with(position1)
