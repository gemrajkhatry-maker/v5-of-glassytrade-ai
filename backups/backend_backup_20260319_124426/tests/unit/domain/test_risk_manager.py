"""Unit tests for Risk Manager domain service."""

import pytest
from app.domain.trading.models.enums import Source, SignalType, SetupType
from app.domain.trading.models.entities import Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.services.risk_manager import RiskManager


class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager()
        self.portfolio = Portfolio.create_default()

    def _make_signal(self, price=100, sl=95, source=Source.AMT) -> Signal:
        return Signal(
            type=SignalType.BUY, price=price, reason="test",
            stop_loss=sl, take_profit=110, timestamp="t",
            setup=SetupType.TREND_MODEL, source=source,
        )

    def test_validates_clean_signal(self):
        sig = self._make_signal()
        assert self.rm.validate(sig, self.portfolio) is True

    def test_rejects_duplicate_source(self):
        sig = self._make_signal()
        self.portfolio.open_position(sig, "BTCUSDT")
        sig2 = self._make_signal()
        assert self.rm.validate(sig2, self.portfolio) is False

    def test_rejects_zero_risk(self):
        sig = self._make_signal(price=100, sl=100)
        assert self.rm.validate(sig, self.portfolio) is False

    def test_allows_different_source(self):
        sig1 = self._make_signal(source=Source.AMT)
        self.portfolio.open_position(sig1, "BTCUSDT")
        sig2 = self._make_signal(source=Source.PREDICTION)
        assert self.rm.validate(sig2, self.portfolio) is True
