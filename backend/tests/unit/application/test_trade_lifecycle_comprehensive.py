"""Comprehensive tests for TradeLifecycleHandler — thin mediator between Portfolio and ExitEngine.

Covers:
1. Cooldown (in_cooldown / post-exit blocking)
2. Partition state management (initialize/clear)
3. check_exits with ExitEngine delegation
4. Stop-loss exit: record_loss + on_stop_out callback
5. No open positions returns False
6. Partition exit logic
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import MagicMock, patch
from decimal import Decimal

from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.domain.fabio_ai.services.exit_engine import ExitEngine, ExitReason, ExitSignal
from app.domain.trading.models.enums import SignalType, Source, SetupType, Side
from app.domain.trading.models.entities import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_real_handler(on_stop_out=None, on_partial_exit=None):
    """Handler with a real ExitEngine."""
    return TradeLifecycleHandler(
        on_stop_out=on_stop_out,
        on_partial_exit=on_partial_exit,
    )


def _make_mocked_handler():
    """Handler with a mocked ExitEngine for isolation."""
    handler = TradeLifecycleHandler()
    ee = MagicMock(spec=ExitEngine)
    ee.check_scale_in.return_value = 0.0
    ee.apply_cvd_kill_signal.return_value = None
    ee.check_position.return_value = None
    ee.check_spread_blowout.return_value = None
    ee.apply_cvd_breakeven.return_value = False
    ee.apply_vwap_trail.return_value = None
    ee.check_imbalance_tighten.return_value = False
    ee.get_position_metrics.return_value = {
        "tick_count": 10,
        "runner_active": False,
        "partial_taken": False,
        "mae": 0.0,
        "mfe": 0.0,
        "cushion_state": "OPEN",
    }
    ee.in_cooldown.return_value = False
    # Mock config with real values
    ee.config = MagicMock()
    ee.config.cooldown_seconds = 30
    handler._exit_engine = ee
    return handler


def _make_portfolio(positions=None):
    portfolio = MagicMock()
    portfolio.positions = positions or []
    portfolio.open_position_ids.return_value = {p.id for p in (positions or [])}
    return portfolio


def _make_real_position(
    pos_id="P1", status="OPEN", symbol="NIFTY25000CE", entry_price=200.0,
    side=Side.LONG, stop_loss=190.0, take_profit=220.0
):
    """Create a real Position entity for testing."""
    pos = Position(
        id=pos_id,
        symbol=symbol,
        side=side,
        source=Source.AMT,
        entry_price=Decimal(str(entry_price)),
        size=Decimal("75.0"),
        stop_loss=Decimal(str(stop_loss)),
        take_profit=Decimal(str(take_profit)),
        initial_stop=Decimal(str(stop_loss)),
        pnl=Decimal("0"),
        entry_time="2025-01-01T10:00:00Z",
    )
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
# 1. Cooldown — now uses ExitEngine.record_exit_time()
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_not_in_cooldown_initially(self):
        handler = _make_real_handler()
        assert handler.in_cooldown("NIFTY25000CE") is False

    def test_in_cooldown_after_exit(self):
        """After record_exit_time, symbol should be in cooldown."""
        handler = _make_real_handler()
        # Record exit time triggers cooldown
        handler.exit_engine.record_exit_time("NIFTY25000CE", current_time=time.time())
        assert handler.in_cooldown("NIFTY25000CE") is True

    def test_cooldown_expires(self):
        """Cooldown should expire after cooldown_seconds has passed."""
        handler = _make_real_handler()
        past_time = time.time() - (handler.exit_engine.config.cooldown_seconds + 1)
        handler.exit_engine.record_exit_time("NIFTY25000CE", current_time=past_time)
        # Cooldown already expired
        assert handler.in_cooldown("NIFTY25000CE") is False

    def test_cooldown_different_symbol_unaffected(self):
        """Cooldown on one symbol must not block another symbol."""
        handler = _make_real_handler()
        handler.exit_engine.record_exit_time("NIFTY25000CE", current_time=time.time())
        # Different symbol is not in cooldown
        assert handler.in_cooldown("BANKNIFTY50000CE") is False


# ---------------------------------------------------------------------------
# 2. Partition state management
# ---------------------------------------------------------------------------


class TestPartitionState:
    def test_initialize_partition_state(self):
        handler = _make_real_handler()
        handler.initialize_partition_state("P1")
        assert "P1" in handler._partition_states

    def test_clear_partition_state(self):
        handler = _make_real_handler()
        handler.initialize_partition_state("P1")
        handler.clear_partition_state("P1")
        assert "P1" not in handler._partition_states

    def test_has_managed_positions_with_partition_state(self):
        handler = _make_real_handler()
        assert handler.has_managed_positions("NIFTY") is False
        handler.initialize_partition_state("P1")
        assert handler.has_managed_positions("NIFTY") is True

    def test_clear_on_position_close(self):
        """_record_close should clear partition state."""
        handler = _make_real_handler()
        handler.initialize_partition_state("P1")
        pos = _make_real_position(pos_id="P1")
        handler._record_close(pos)
        assert "P1" not in handler._partition_states


# ---------------------------------------------------------------------------
# 3. check_exits delegation to ExitEngine
# ---------------------------------------------------------------------------


class TestCheckExits:
    def test_check_exits_returns_false_with_empty_portfolio(self):
        handler = _make_mocked_handler()
        portfolio = _make_portfolio([])
        result = handler.check_exits(portfolio, 200.0)
        assert result is False

    def test_check_exits_skips_closed_positions(self):
        """CLOSED positions should be skipped."""
        handler = _make_mocked_handler()
        pos = _make_real_position(status="CLOSED")
        pos.status = "CLOSED"  # Simulate already closed
        portfolio = _make_portfolio([pos])

        result = handler.check_exits(portfolio, 200.0)
        assert result is False
        handler.exit_engine.check_position.assert_not_called()

    def test_check_exits_calls_exit_engine_methods(self):
        """check_exits should call ExitEngine methods for open positions."""
        handler = _make_mocked_handler()
        pos = _make_real_position()
        pos.tick_count = 5  # Past grace period
        portfolio = _make_portfolio([pos])

        handler.check_exits(portfolio, 200.0, cvd_slope=0.5, cvd_divergence="BEARISH_DIV")

        # Should call various exit engine methods
        handler.exit_engine.check_scale_in.assert_called_once()
        handler.exit_engine.apply_cvd_breakeven.assert_called_once()
        handler.exit_engine.check_position.assert_called_once()

    def test_check_exits_respects_cvd_grace_period(self):
        """CVD kill signal should be skipped for first 3 ticks."""
        handler = _make_mocked_handler()
        pos = _make_real_position()
        pos.tick_count = 2  # In grace period
        portfolio = _make_portfolio([pos])

        handler.check_exits(portfolio, 200.0, cvd_divergence="BEARISH_DIV")

        # CVD kill should NOT be called during grace period
        handler.exit_engine.apply_cvd_kill_signal.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Stop-loss exit: record_loss + on_stop_out callback
# ---------------------------------------------------------------------------


class TestStopLossExit:
    def test_stop_loss_triggers_record_loss_and_callback(self):
        on_stop_out = MagicMock()
        handler = _make_mocked_handler()
        handler._on_stop_out = on_stop_out

        pos = _make_real_position(symbol="NIFTY25000CE", side=Side.LONG)
        portfolio = _make_portfolio([pos])

        # check_position returns STOP_LOSS signal
        exit_sig = ExitSignal(pos.id, ExitReason.STOP_LOSS, 185.0)
        handler.exit_engine.check_position.return_value = exit_sig

        result = handler.check_exits(portfolio, 185.0)

        assert result is True
        handler.exit_engine.record_loss.assert_called_once()
        handler.exit_engine.record_exit_time.assert_called_once()
        on_stop_out.assert_called_once()

    def test_take_profit_exit_does_not_record_loss(self):
        handler = _make_mocked_handler()
        pos = _make_real_position()
        portfolio = _make_portfolio([pos])

        exit_sig = ExitSignal(pos.id, ExitReason.TAKE_PROFIT, 225.0)
        handler.exit_engine.check_position.return_value = exit_sig

        result = handler.check_exits(portfolio, 225.0)

        assert result is True
        handler.exit_engine.record_loss.assert_not_called()

    def test_time_stop_exit_does_not_record_loss(self):
        handler = _make_mocked_handler()
        pos = _make_real_position()
        portfolio = _make_portfolio([pos])

        exit_sig = ExitSignal(pos.id, ExitReason.TIME_STOP, 200.0)
        handler.exit_engine.check_position.return_value = exit_sig

        result = handler.check_exits(portfolio, 200.0)

        assert result is True
        handler.exit_engine.record_loss.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Spread blowout check
# ---------------------------------------------------------------------------


class TestSpreadBlowout:
    def test_spread_blowout_closes_position(self):
        handler = _make_mocked_handler()
        pos = _make_real_position()
        portfolio = _make_portfolio([pos])

        # Spread blowout signal
        blowout_sig = ExitSignal(pos.id, ExitReason.SPREAD_BLOWOUT, 198.0)
        handler.exit_engine.check_spread_blowout.return_value = blowout_sig

        order_book = MagicMock()
        order_book.bids = [MagicMock(price=197.0)]
        order_book.asks = [MagicMock(price=203.0)]

        result = handler.check_exits(portfolio, 200.0, order_book=order_book)

        assert result is True
        portfolio.close_position.assert_called_once()
        handler.exit_engine.record_exit_time.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Scale-in check
# ---------------------------------------------------------------------------


class TestScaleIn:
    def test_scale_in_adds_to_position(self):
        handler = _make_mocked_handler()
        pos = _make_real_position()
        portfolio = _make_portfolio([pos])

        # Scale-in returns 0.3 (30% add)
        handler.exit_engine.check_scale_in.return_value = 0.3

        handler.check_exits(portfolio, 205.0)

        portfolio.add_to_position.assert_called_once_with(pos.id, 0.3, 205.0)


# ---------------------------------------------------------------------------
# 7. CVD kill signal
# ---------------------------------------------------------------------------


class TestCVDKillSignal:
    def test_cvd_kill_closes_position(self):
        handler = _make_mocked_handler()
        pos = _make_real_position()
        pos.tick_count = 5  # Past grace period
        portfolio = _make_portfolio([pos])

        cvd_exit = ExitSignal(pos.id, ExitReason.SCRATCH, 200.0)
        handler.exit_engine.apply_cvd_kill_signal.return_value = cvd_exit

        result = handler.check_exits(portfolio, 200.0, cvd_divergence="BEARISH_DIV")

        assert result is True
        portfolio.close_position.assert_called_once()


# ---------------------------------------------------------------------------
# 8. No open positions
# ---------------------------------------------------------------------------


class TestNoPositions:
    def test_check_exits_returns_false_with_empty_portfolio(self):
        handler = _make_real_handler()
        portfolio = _make_portfolio([])
        result = handler.check_exits(portfolio, 200.0)
        assert result is False

    def test_has_managed_positions_false_initially(self):
        handler = _make_real_handler()
        assert handler.has_managed_positions("NIFTY25000CE") is False


# ---------------------------------------------------------------------------
# 9. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_trade_manager_alias(self):
        """trade_manager property should be an alias for exit_engine."""
        handler = _make_real_handler()
        assert handler.trade_manager is handler.exit_engine

    def test_exit_engine_property(self):
        """exit_engine property should expose the engine."""
        handler = _make_real_handler()
        assert isinstance(handler.exit_engine, ExitEngine)
