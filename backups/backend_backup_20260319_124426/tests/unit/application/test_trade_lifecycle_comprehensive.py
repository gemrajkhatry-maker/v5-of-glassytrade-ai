"""Comprehensive tests for TradeLifecycleHandler.

Covers gaps left by test_trade_lifecycle_gaps.py:
1. Cooldown (in_cooldown / post-exit blocking)
2. register_position market_state normalization ('Trending' → 'IMBALANCED')
3. on_partial_exit callback signature
4. sync_closed: positions closed externally are unregistered from TradeManager
5. CVD grace period: kill signal skipped for first 3 ticks
6. Full exit path: record_loss + on_stop_out called on STOP_LOSS
7. Partial exit does NOT unregister the position (runner still active)
8. check_exits returns False when no positions open
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.domain.fabio_ai.services.trade_manager import ExitReason, TradeManager
from app.domain.trading.models.enums import SignalType, Source, SetupType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_real_handler(on_stop_out=None, on_partial_exit=None):
    """Handler with a real TradeManager (not mocked)."""
    return TradeLifecycleHandler(
        on_stop_out=on_stop_out,
        on_partial_exit=on_partial_exit,
    )


def _make_mocked_handler():
    """Handler with a fully mocked TradeManager for isolation."""
    handler = TradeLifecycleHandler()
    tm = (
        MagicMock()
    )  # plain MagicMock — spec=TradeManager would block .config attr assignment
    tm.check_scale_in.return_value = 0.0
    tm.apply_cvd_kill_signal.return_value = None
    tm.check_position.return_value = None
    tm.check_spread_blowout.return_value = None
    tm.sync_with_open_position_ids.return_value = ()
    consistency = MagicMock()
    consistency.unmanaged_open_ids = ()
    consistency.stale_managed_ids = ()
    consistency.is_consistent = True
    tm.get_position_consistency.return_value = consistency
    tm._positions = {}
    # Pre-configure the config mock with real default values
    tm.config = MagicMock()
    tm.config.partial_size_pct = 0.50
    tm.config.runner_close_pct = 0.75
    tm.config.cooldown_seconds = 30
    handler._trade_manager = tm
    return handler


def _make_portfolio(positions=None):
    portfolio = MagicMock()
    portfolio.positions = positions or []
    return portfolio


def _make_position(
    pos_id="P1", status="OPEN", symbol="NIFTY25000CE", entry_price=200.0
):
    pos = MagicMock()
    pos.id = pos_id
    pos.status = status
    pos.symbol = symbol
    pos.entry_price = entry_price
    pos.size = 75.0
    pos.side = MagicMock()
    pos.side.value = "LONG"
    return pos


def _make_signal(is_buy=True, sl=190.0, tp=220.0, market_state="BALANCED"):
    sig = MagicMock()
    sig.type = SignalType.BUY if is_buy else SignalType.SELL
    sig.stop_loss = sl
    sig.take_profit = tp
    sig.metadata = {
        "allow_trail": False,
        "scale_in": False,
        "market_state_model": market_state,
        "session_phase": "",
        "is_expiry": False,
    }
    return sig


# ---------------------------------------------------------------------------
# 1. Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_not_in_cooldown_initially(self):
        handler = _make_real_handler()
        assert handler.in_cooldown("NIFTY25000CE") is False

    def test_in_cooldown_after_exit(self):
        """After unregistering a position, symbol should be in cooldown."""
        import time

        handler = _make_real_handler()
        # Register then immediately unregister (simulating exit)
        handler._trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY25000CE",
            side="LONG",
            entry_price=200.0,
            stop_loss=190.0,
            take_profit=220.0,
        )
        handler._trade_manager.unregister_position("P1", current_time=time.time())
        assert handler.in_cooldown("NIFTY25000CE") is True

    def test_cooldown_expires(self):
        """Cooldown should expire after cooldown_seconds has passed."""
        import time

        handler = _make_real_handler()
        handler._trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY25000CE",
            side="LONG",
            entry_price=200.0,
            stop_loss=190.0,
            take_profit=220.0,
        )
        past_time = time.time() - (handler._trade_manager.config.cooldown_seconds + 1)
        handler._trade_manager.unregister_position("P1", current_time=past_time)
        # Cooldown already expired
        assert handler.in_cooldown("NIFTY25000CE") is False

    def test_cooldown_different_symbol_unaffected(self):
        """Cooldown on one symbol must not block another symbol."""
        import time

        handler = _make_real_handler()
        handler._trade_manager.register_position(
            position_id="P1",
            symbol="NIFTY25000CE",
            side="LONG",
            entry_price=200.0,
            stop_loss=190.0,
            take_profit=220.0,
        )
        handler._trade_manager.unregister_position("P1", current_time=time.time())
        # Different symbol is not in cooldown
        assert handler.in_cooldown("BANKNIFTY50000CE") is False


# ---------------------------------------------------------------------------
# 2. register_position — market_state normalization
# ---------------------------------------------------------------------------


class TestRegisterPositionNormalization:
    def test_trending_normalizes_to_imbalanced(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        sig = _make_signal(market_state="Trending")
        handler.register_position("NIFTY25000CE", pos, sig)
        _, kwargs = handler._trade_manager.register_position.call_args
        assert kwargs["market_state"] == "IMBALANCED"

    def test_imbalance_keyword_normalizes_to_imbalanced(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        sig = _make_signal(market_state="IMBALANCED_BREAKOUT")
        handler.register_position("NIFTY25000CE", pos, sig)
        _, kwargs = handler._trade_manager.register_position.call_args
        assert kwargs["market_state"] == "IMBALANCED"

    def test_balanced_stays_balanced(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        sig = _make_signal(market_state="BALANCED")
        handler.register_position("NIFTY25000CE", pos, sig)
        _, kwargs = handler._trade_manager.register_position.call_args
        assert kwargs["market_state"] == "BALANCED"

    def test_unknown_defaults_to_balanced(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        sig = _make_signal(market_state="CHOP")
        handler.register_position("NIFTY25000CE", pos, sig)
        _, kwargs = handler._trade_manager.register_position.call_args
        assert kwargs["market_state"] == "BALANCED"

    def test_allow_trail_passed_through(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        sig = _make_signal()
        sig.metadata["allow_trail"] = True
        handler.register_position("NIFTY25000CE", pos, sig)
        _, kwargs = handler._trade_manager.register_position.call_args
        assert kwargs["allow_trail"] is True

    def test_short_signal_registers_as_short(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        sig = _make_signal(is_buy=False)
        handler.register_position("NIFTY25000PE", pos, sig)
        _, kwargs = handler._trade_manager.register_position.call_args
        assert kwargs["side"] == "SHORT"


# ---------------------------------------------------------------------------
# 3. on_partial_exit callback signature
# ---------------------------------------------------------------------------


class TestPartialExitCallback:
    def test_on_partial_exit_called_with_correct_args(self):
        callback = MagicMock()
        handler = _make_mocked_handler()
        handler._on_partial_exit = callback

        pos = _make_position(pos_id="P1")
        pos.entry_price = 200.0
        pos.size = 75.0
        portfolio = _make_portfolio([pos])
        portfolio.partial_close_position.return_value = 150.0  # realized PnL

        # Make check_position return a PARTIAL_TAKE_PROFIT signal
        exit_sig = MagicMock()
        exit_sig.reason = ExitReason.PARTIAL_TAKE_PROFIT
        exit_sig.exit_price = 210.0
        handler._trade_manager.check_position.return_value = exit_sig

        # mp mock — not runner_active
        mp = MagicMock()
        mp.runner_active = False
        mp.tick_count = 10
        handler._trade_manager._positions = {"P1": mp}
        # Must mock get_position_metrics to return the mock's attributes
        handler._trade_manager.get_position_metrics.return_value = {
            "runner_active": False,
            "tick_count": 10,
            "partial_taken": False,
            "trailing_active": False,
            "mae": 0.0,
            "mfe": 0.0,
        }
        handler._trade_manager.config.partial_size_pct = 0.50
        handler._trade_manager.config.runner_close_pct = 0.75

        result = handler.check_exits(portfolio, 210.0)

        assert result is False  # partial = position still open
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "P1"  # pos_id
        assert args[2] == 200.0  # entry_price
        assert args[3] == 210.0  # exit_price
        assert args[4] == 0.50  # partial_pct
        assert args[7] == 150.0  # realized_pnl

    def test_runner_uses_runner_close_pct(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])
        portfolio.partial_close_position.return_value = 100.0

        exit_sig = MagicMock()
        exit_sig.reason = ExitReason.PARTIAL_TAKE_PROFIT
        exit_sig.exit_price = 215.0
        handler._trade_manager.check_position.return_value = exit_sig

        mp = MagicMock()
        mp.runner_active = True  # ← runner mode
        mp.tick_count = 10
        handler._trade_manager._positions = {"P1": mp}
        handler._trade_manager.config.runner_close_pct = 0.75
        handler._trade_manager.config.partial_size_pct = 0.50

        handler.check_exits(portfolio, 215.0)

        # Close should use 75% (runner_close_pct), not 50%
        portfolio.partial_close_position.assert_called_once_with(
            "P1", 0.75, 215.0, ExitReason.PARTIAL_TAKE_PROFIT
        )


# ---------------------------------------------------------------------------
# 4. sync_closed
# ---------------------------------------------------------------------------


class TestSyncClosed:
    def test_sync_closed_unregisters_all_positions(self):
        handler = _make_mocked_handler()
        pos1 = _make_position("P1")
        pos2 = _make_position("P2")

        handler.sync_closed([pos1, pos2])

        handler._trade_manager.unregister_position.assert_any_call("P1")
        handler._trade_manager.unregister_position.assert_any_call("P2")
        assert handler._trade_manager.unregister_position.call_count == 2

    def test_sync_closed_empty_list_is_noop(self):
        handler = _make_mocked_handler()
        handler.sync_closed([])
        handler._trade_manager.unregister_position.assert_not_called()

    def test_reconcile_portfolio_removes_orphaned_managed_positions(self):
        handler = _make_mocked_handler()
        open_pos = _make_position("P1", status="OPEN")
        portfolio = _make_portfolio([open_pos])

        handler.reconcile_portfolio(portfolio, symbol="NIFTY25000CE")

        handler._trade_manager.sync_with_open_position_ids.assert_called_once_with(
            {"P1"}, symbol="NIFTY25000CE"
        )

    def test_get_position_consistency_passes_open_ids_to_trade_manager(self):
        handler = _make_mocked_handler()
        open_pos = _make_position("P1", status="OPEN")
        portfolio = _make_portfolio([open_pos])
        expected = MagicMock()
        handler._trade_manager.get_position_consistency.return_value = expected

        result = handler.get_position_consistency(portfolio, symbol="NIFTY25000CE")

        assert result is expected
        handler._trade_manager.get_position_consistency.assert_called_once_with(
            {"P1"}, symbol="NIFTY25000CE"
        )

    def test_ensure_position_consistency_reconciles_then_rechecks(self):
        handler = _make_mocked_handler()
        portfolio = _make_portfolio([_make_position("P1", status="OPEN")])
        after = MagicMock()
        after.unmanaged_open_ids = ()
        handler._trade_manager.get_position_consistency.return_value = after

        result = handler.ensure_position_consistency(portfolio, symbol="NIFTY25000CE")

        assert result is after
        handler._trade_manager.sync_with_open_position_ids.assert_called_once_with(
            {"P1"}, symbol="NIFTY25000CE"
        )
        assert handler._trade_manager.get_position_consistency.call_count == 1

    def test_sync_closed_prevents_double_close(self):
        """After sync_closed, check_exits should not trigger on already closed positions."""
        handler = _make_mocked_handler()
        pos = _make_position("P1", status="CLOSED")
        portfolio = _make_portfolio([pos])

        # Position is already CLOSED — check_exits loop should skip it
        result = handler.check_exits(portfolio, 200.0)
        assert result is False
        handler._trade_manager.check_position.assert_not_called()


# ---------------------------------------------------------------------------
# 5. CVD grace period (first 3 ticks protected)
# ---------------------------------------------------------------------------


class TestCVDGracePeriod:
    def test_cvd_kill_skipped_in_first_3_ticks(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])
        consistency = MagicMock()
        consistency.unmanaged_open_ids = ()
        handler._trade_manager.get_position_consistency.return_value = consistency

        # tick_count = 2 → still in grace period
        mp = MagicMock()
        mp.tick_count = 2
        handler._trade_manager._positions = {"P1": mp}
        handler._trade_manager.get_position_metrics.return_value = {
            "runner_active": False,
            "tick_count": 2,
            "partial_taken": False,
            "trailing_active": False,
            "mae": 0.0,
            "mfe": 0.0,
        }

        handler.check_exits(portfolio, 190.0, cvd_divergence="BEARISH_DIV")
        handler._trade_manager.apply_cvd_kill_signal.assert_not_called()

    def test_cvd_kill_applied_after_grace_period(self):
        handler = _make_mocked_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])
        consistency = MagicMock()
        consistency.unmanaged_open_ids = ()
        handler._trade_manager.get_position_consistency.return_value = consistency

        # tick_count = 5 → past grace period
        mp = MagicMock()
        mp.tick_count = 5
        handler._trade_manager._positions = {"P1": mp}
        handler._trade_manager.apply_cvd_kill_signal.return_value = None
        handler._trade_manager.get_position_metrics.return_value = {
            "runner_active": False,
            "tick_count": 5,
            "partial_taken": False,
            "trailing_active": False,
            "mae": 0.0,
            "mfe": 0.0,
        }

        handler.check_exits(portfolio, 190.0, cvd_divergence="BEARISH_DIV")
        handler._trade_manager.apply_cvd_kill_signal.assert_called_once_with(
            "P1", "BEARISH_DIV", 190.0
        )


# ---------------------------------------------------------------------------
# 6. Stop-loss exit: record_loss + on_stop_out both called
# ---------------------------------------------------------------------------


class TestStopLossExit:
    def test_stop_loss_triggers_record_loss_and_callback(self):
        on_stop_out = MagicMock()
        handler = _make_mocked_handler()
        handler._on_stop_out = on_stop_out

        pos = _make_position("P1", symbol="NIFTY25000CE")
        pos.side.value = "LONG"
        portfolio = _make_portfolio([pos])
        consistency = MagicMock()
        consistency.unmanaged_open_ids = ()
        handler._trade_manager.get_position_consistency.return_value = consistency

        exit_sig = MagicMock()
        exit_sig.reason = ExitReason.STOP_LOSS
        exit_sig.exit_price = 185.0
        handler._trade_manager.check_position.return_value = exit_sig
        mp = MagicMock()
        mp.tick_count = 10
        handler._trade_manager._positions = {"P1": mp}

        result = handler.check_exits(portfolio, 185.0)

        assert result is True
        handler._trade_manager.record_loss.assert_called_once_with("NIFTY25000CE")
        on_stop_out.assert_called_once_with(pos.entry_price, "LONG")

    def test_take_profit_exit_does_not_record_loss(self):
        handler = _make_mocked_handler()
        pos = _make_position("P1")
        portfolio = _make_portfolio([pos])
        consistency = MagicMock()
        consistency.unmanaged_open_ids = ()
        handler._trade_manager.get_position_consistency.return_value = consistency

        exit_sig = MagicMock()
        exit_sig.reason = ExitReason.TAKE_PROFIT
        exit_sig.exit_price = 225.0
        handler._trade_manager.check_position.return_value = exit_sig
        mp = MagicMock()
        mp.tick_count = 10
        handler._trade_manager._positions = {"P1": mp}

        result = handler.check_exits(portfolio, 225.0)

        assert result is True
        handler._trade_manager.record_loss.assert_not_called()

    def test_time_stop_exit_does_not_record_loss(self):
        handler = _make_mocked_handler()
        pos = _make_position("P1")
        portfolio = _make_portfolio([pos])

        exit_sig = MagicMock()
        exit_sig.reason = ExitReason.TIME_STOP
        exit_sig.exit_price = 200.0
        handler._trade_manager.check_position.return_value = exit_sig
        mp = MagicMock()
        mp.tick_count = 10
        handler._trade_manager._positions = {"P1": mp}

        result = handler.check_exits(portfolio, 200.0)

        assert result is True
        handler._trade_manager.record_loss.assert_not_called()


# ---------------------------------------------------------------------------
# 7. No open positions
# ---------------------------------------------------------------------------


class TestNoPositions:
    def test_check_exits_returns_false_with_empty_portfolio(self):
        handler = _make_mocked_handler()
        portfolio = _make_portfolio([])
        result = handler.check_exits(portfolio, 200.0)
        assert result is False
        handler._trade_manager.check_position.assert_not_called()

    def test_has_managed_positions_false_initially(self):
        handler = _make_real_handler()
        assert handler.has_managed_positions("NIFTY25000CE") is False
