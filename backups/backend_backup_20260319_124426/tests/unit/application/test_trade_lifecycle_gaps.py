"""Tests for TradeLifecycleHandler gap wiring (spread blowout, VWAP trail, imbalance tighten)."""
import pytest
from unittest.mock import MagicMock, patch
from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
from app.domain.fabio_ai.services.trade_manager import ExitReason


def _make_handler():
    handler = TradeLifecycleHandler()
    handler._trade_manager = MagicMock()
    handler._trade_manager.check_scale_in.return_value = 0
    handler._trade_manager.apply_cvd_kill_signal.return_value = None
    handler._trade_manager.check_position.return_value = None
    handler._trade_manager._positions = {}
    return handler


def _make_portfolio(positions=None):
    portfolio = MagicMock()
    portfolio.positions = positions or []
    return portfolio


def _make_position(pos_id="P1", status="OPEN"):
    pos = MagicMock()
    pos.id = pos_id
    pos.status = status
    return pos


class TestSpreadBlowout:
    def test_spread_blowout_triggers_exit(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        order_book = MagicMock()
        order_book.bids = [MagicMock(price=100.0)]
        order_book.asks = [MagicMock(price=104.0)]

        blowout_signal = MagicMock()
        blowout_signal.exit_price = 102.0
        blowout_signal.reason = ExitReason.SPREAD_BLOWOUT
        handler._trade_manager.check_spread_blowout.return_value = blowout_signal

        result = handler.check_exits(portfolio, 102.0, order_book=order_book)
        assert result is True
        portfolio.close_position.assert_called_once()
        handler._trade_manager.unregister_position.assert_called_once_with("P1")

    def test_no_blowout_without_orderbook(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        result = handler.check_exits(portfolio, 100.0, order_book=None)
        handler._trade_manager.check_spread_blowout.assert_not_called()

    def test_no_blowout_when_spread_ok(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        order_book = MagicMock()
        order_book.bids = [MagicMock(price=100.0)]
        order_book.asks = [MagicMock(price=100.5)]
        handler._trade_manager.check_spread_blowout.return_value = None

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

        handler.check_exits(portfolio, 100.0, amt_result=amt)
        handler._trade_manager.apply_vwap_trail.assert_called_once()

    def test_vwap_trail_not_called_without_amt(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        handler.check_exits(portfolio, 100.0, amt_result=None)
        handler._trade_manager.apply_vwap_trail.assert_not_called()


class TestImbalanceTighten:
    def test_imbalance_tighten_called_with_imbalances(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        imbalances = [MagicMock(), MagicMock()]
        handler.check_exits(portfolio, 100.0, imbalances=imbalances)
        handler._trade_manager.check_imbalance_tighten.assert_called_once()

    def test_imbalance_tighten_not_called_without_data(self):
        handler = _make_handler()
        pos = _make_position()
        portfolio = _make_portfolio([pos])

        handler.check_exits(portfolio, 100.0, imbalances=None)
        handler._trade_manager.check_imbalance_tighten.assert_not_called()
