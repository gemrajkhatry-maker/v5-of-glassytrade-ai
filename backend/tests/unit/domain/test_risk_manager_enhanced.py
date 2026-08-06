"""Tests for enhanced RiskManager — circuit breakers, position limits, consecutive losses."""

import pytest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch

from app.domain.trading.models.enums import Source, SignalType, SetupType
from app.domain.trading.models.entities import Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.services.risk_manager import RiskManager


def _make_signal(price=100, sl=95, source=Source.AMT) -> Signal:
    return Signal(
        type=SignalType.BUY, price=price, reason="test",
        stop_loss=sl, take_profit=110, timestamp="t",
        setup=SetupType.TREND_MODEL, source=source,
    )


class TestCircuitBreakers:
    def setup_method(self):
        self.rm = RiskManager()
        self.portfolio = Portfolio.create_default()
        # Initialize daily state
        self.rm._daily.starting_equity = self.portfolio.equity

    def test_halts_after_consecutive_losses(self):
        sig = _make_signal()
        # Threshold is now 5 consecutive losses (was 10 — tightened for scalping)
        for _ in range(5):
            self.rm.record_trade_result(-100, self.portfolio)

        assert self.rm.is_halted
        assert "consecutive losses" in self.rm.halt_reason
        assert self.rm.validate(sig, self.portfolio) is False

    def test_winning_trade_resets_consecutive_count(self):
        self.rm.record_trade_result(-100, self.portfolio)
        self.rm.record_trade_result(-100, self.portfolio)
        self.rm.record_trade_result(500, self.portfolio)  # win resets
        self.rm.record_trade_result(-100, self.portfolio)

        assert not self.rm.is_halted
        assert self.rm._daily.consecutive_losses == 1

    def test_halts_on_daily_drawdown(self):
        # MAX_DAILY_DRAWDOWN_PCT = 2% of peak equity.
        # INITIAL_CAPITAL is 5M, so halt requires a loss >= 100k (2%).
        self.portfolio.balance -= 110_000
        self.portfolio.equity = self.portfolio.balance
        self.rm.record_trade_result(-110_000, self.portfolio)

        assert self.rm.is_halted
        assert "drawdown" in self.rm.halt_reason

    def test_no_halt_under_drawdown_limit(self):
        # 1% loss (below 2% threshold per FR-10-04) — should NOT halt
        self.portfolio.balance -= 10_000
        self.portfolio.equity = self.portfolio.balance
        self.rm.record_trade_result(-10_000, self.portfolio)
        assert not self.rm.is_halted


class TestMaxConcurrentPositions:
    def setup_method(self):
        self.rm = RiskManager()
        self.portfolio = Portfolio.create_default()

    def test_rejects_beyond_max_positions(self):
        """Max concurrent positions is 5. Fill up and verify rejection."""
        sources = [Source.AMT, Source.PREDICTION, Source.LLM]
        for src in sources:
            sig = _make_signal(source=src)
            self.portfolio.open_position(sig, "BTCUSDT")

        assert len(self.portfolio.positions) == 3
        # With MAX_CONCURRENT_POSITIONS=5, 3 positions is still under limit
        assert len(self.portfolio.positions) < self.rm.MAX_CONCURRENT_POSITIONS
        # The validate method should still accept (under cap)
        sig4 = _make_signal(source=Source.RL)
        assert self.rm.validate(sig4, self.portfolio) is True


class TestDailyReset:
    def setup_method(self):
        self.rm = RiskManager()
        self.portfolio = Portfolio.create_default()

    def test_resets_on_new_day(self):
        # Trigger halt via 5 consecutive losses
        for _ in range(5):
            self.rm.record_trade_result(-100, self.portfolio)
        assert self.rm.is_halted

        # Simulate next day (risk_manager uses datetime.now(_IST).date())
        with patch("app.domain.trading.services.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2099, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            sig = _make_signal()
            result = self.rm.validate(sig, self.portfolio)
            assert result is True
            assert not self.rm.is_halted
