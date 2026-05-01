"""Tests for TradeLifecycleHandler gap wiring (spread blowout, VWAP trail, imbalance tighten)."""
import pytest
from unittest.mock import MagicMock
from decimal import Decimal

from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.domain.fabio_ai.services.exit_engine import ExitEngine, ExitReason, ExitSignal
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side, Source


def _make_handler():
    handler = TradeLifecycleHandler()
    # Mock the ExitEngine
    handler._exit_engine = MagicMock(spec=ExitEngine)
    handler._exit_engine.check_scale_in.return_value = 0
    handler._exit_engine.apply_cvd_kill_signal.return_value = None
    handler._exit_engine.check_position.return_value = None
    handler._exit_engine.apply_cvd_breakeven.return_value = False
    handler._exit_engine.apply_vwap_trail.return_value = None
    handler._exit_engine.check_imbalance_tighten.return_value = False
    handler._exit_engine.get_position_metrics.return_value = {"tick_count": 10}
    handler._exit_engine.config = MagicMock()
    handler._exit_engine.config.cooldown_seconds = 30
    return handler


def _make_portfolio(positions=None):
    portfolio = MagicMock()
    portfolio.positions = positions or []
    return portfolio


def _make_position(pos_id="P1", status="OPEN", symbol="NIFTY"):
    pos = Position(
        id=pos_id,
        symbol=symbol,
        side=Side.LONG,
        source=Source.AMT,
        entry_price=Decimal("100.0"),
        size=Decimal("75.0"),
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("110.0"),
        initial_stop=Decimal("95.0"),
        pnl=Decimal("0"),
        entry_time="2025-01-01T10:00:00Z",
    )
    return pos


class TestSpreadBlowout:
    def test_spread_blowout_triggers_exit(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        order_book = MagicMock()
        order_book.bids = [MagicMock(price=100.0)]
        order_book.asks = [MagicMock(price=104.0)]

        blowout_signal = ExitSignal(pos.id, ExitReason.SPREAD_BLOWOUT, 102.0)
        handler._exit_engine.check_spread_blowout.return_value = blowout_signal

        result = handler.check_exits(portfolio, 102.0, order_book=order_book)
        assert result is True
        portfolio.close_position.assert_called_once()
        handler._exit_engine.record_exit_time.assert_called_once()

    def test_no_blowout_without_orderbook(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        result = handler.check_exits(portfolio, 100.0, order_book=None)
        handler._exit_engine.check_spread_blowout.assert_not_called()

    def test_no_blowout_when_spread_ok(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        order_book = MagicMock()
        order_book.bids = [MagicMock(price=100.0)]
        order_book.asks = [MagicMock(price=100.5)]
        handler._exit_engine.check_spread_blowout.return_value = None

        result = handler.check_exits(portfolio, 100.0, order_book=order_book)
        assert result is False


class TestVWAPTrail:
    def test_vwap_trail_called_with_amt_result(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        amt = MagicMock()
        amt.session_vwap = 100.0
        amt.vwap_upper_1 = 101.0
        amt.vwap_lower_1 = 99.0
        amt.vwap_upper_2 = 102.0
        amt.vwap_lower_2 = 98.0
        # Force aggression_score to be a real number, not a MagicMock
        amt.aggression_score = 0.0

        handler.check_exits(portfolio, 100.0, amt_result=amt)
        handler._exit_engine.apply_vwap_trail.assert_called_once()

    def test_vwap_trail_not_called_without_amt(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        handler.check_exits(portfolio, 100.0, amt_result=None)
        handler._exit_engine.apply_vwap_trail.assert_not_called()


class TestImbalanceTighten:
    def test_imbalance_tighten_called_with_imbalances(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        imbalances = [MagicMock(), MagicMock()]
        handler.check_exits(portfolio, 100.0, imbalances=imbalances)
        handler._exit_engine.check_imbalance_tighten.assert_called_once()

    def test_imbalance_tighten_not_called_without_data(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        handler.check_exits(portfolio, 100.0, imbalances=None)
        handler._exit_engine.check_imbalance_tighten.assert_not_called()
