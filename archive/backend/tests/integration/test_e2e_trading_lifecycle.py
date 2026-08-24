"""End-to-end tests — full trading lifecycle, WebSocket, system endpoints,
commission/slippage pipeline, and event immutability.
"""

from __future__ import annotations
from decimal import Decimal
import json
import math
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from quant.contracts.aggregates import (
    Portfolio, COMMISSION_PER_LOT, SLIPPAGE_PCT,
)
from quant.contracts.entities import Position, Signal
from quant.contracts.enums import (
    Side, Source, PositionStatus, SignalType, SetupType,
)
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.data_generator import generate_market_data
from app.application.services.trading_session import TradingSessionService
from quant.contracts.events import TickReceived
from app.application.services.trading_session import SystemRiskState
from quant.contracts.ports.probability_inference import NoOpProbabilityAdapter
from quant.inference.generative_ai import GenerativeAIService


def _make_tick(close: float = 100.0, time: str = "2026-01-01T10:00:00Z", **overrides) -> OHLC:
    defaults = dict(
        time=time, open=close, high=close * 1.01,
        low=close * 0.99, close=close, volume=1000,
        vwap=close, taker_buy_volume=600, delta=200,
    )
    defaults.update(overrides)
    return OHLC(**defaults)


def _make_signal(price=100, sl=90, tp=120, source=Source.AMT, sig_type=SignalType.BUY, metadata=None) -> Signal:
    return Signal(
        type=sig_type, price=price, reason="test signal",
        stop_loss=sl, take_profit=tp, timestamp="2026-01-01T10:00:00Z",
        setup=SetupType.TREND_MODEL, source=source, metadata=metadata,
    )


def _create_session_service():
    """Create a TradingSessionService with stub dependencies."""
    broker = PaperBrokerAdapter()
    from quant.contracts.ports.llm_inference import ILLMInference
    class _StubLLM(ILLMInference):
        def predict(self, instruction, input_text): return "Trigger: **Stay Flat**"
        def is_ready(self): return True
    gen_ai = GenerativeAIService(llm_adapter=_StubLLM())
    return TradingSessionService(
        broker=broker, gen_ai_service=gen_ai,
        probability_engine=NoOpProbabilityAdapter(), exchange_config=None,
    )


class TestFullTradingLifecycle:
    """Tick → Analysis → Signal → Position → Close."""

    def setup_method(self):
        self.session = _create_session_service()

    def test_pipeline_200_candles_produces_valid_state(self):
        """Feed 200 candles and verify state shape."""
        data = generate_market_data(200, 50000, "volatile")
        state = None
        for tick in data:
            state = self.session.process_tick("TESTOPT", tick)
        assert state is not None
        assert "portfolio" in state
        assert "amt" in state

    def test_position_opens_with_slipped_entry(self):
        """When a position opens, entry price differs from signal due to slippage."""
        portfolio = Portfolio.create_default()
        signal = _make_signal(price=1000, sl=950, tp=1100)
        pos = portfolio.open_position(signal, "TESTOPT")
        assert pos is not None
        expected_slipped = 1000 * (1 + SLIPPAGE_PCT)
        assert pos.entry_price == pytest.approx(expected_slipped, rel=1e-6)

    def test_position_closes_with_slipped_exit_and_commission(self):
        """Full open → TP close → verify slippage + commission deducted."""
        portfolio = Portfolio.create_default()
        initial_balance = portfolio.balance
        signal = _make_signal(price=1000, sl=900, tp=1200)
        pos = portfolio.open_position(signal, "TESTOPT")
        assert pos is not None
        entry = pos.entry_price
        size = pos.size
        tick = _make_tick(close=1200)
        closed = portfolio.process_tick(tick)
        assert len(closed) == 1
        closed_pos = closed[0]
        expected_exit = 1200 * (1 - SLIPPAGE_PCT)
        assert closed_pos.exit_price == pytest.approx(expected_exit, rel=1e-6)
        raw_pnl = (expected_exit - entry) * size
        expected_pnl = raw_pnl - COMMISSION_PER_LOT
        assert closed_pos.pnl == pytest.approx(expected_pnl, rel=1e-4)
        assert portfolio.balance == pytest.approx(initial_balance + expected_pnl, rel=1e-4)

    def test_equity_history_populated_after_ticks(self):
        """Equity history should have entries after enough ticks."""
        data = generate_market_data(100, 100, "bullish")
        for tick in data:
            self.session.process_tick("TESTOPT", tick)
        sess = self.session.get_or_create_session("TESTOPT")
        assert len(sess.portfolio.history) > 0

    def test_closed_trades_tracked(self):
        """Positions that close via SL/TP should appear in closed_trades."""
        portfolio = Portfolio.create_default()
        signal = _make_signal(price=100, sl=95, tp=110)
        portfolio.open_position(signal, "TESTOPT")
        tick = _make_tick(close=94)
        closed = portfolio.process_tick(tick)
        assert len(closed) == 1
        assert len(portfolio.closed_trades) == 1
        assert portfolio.closed_trades[0].status == PositionStatus.CLOSED

    def test_multiple_symbols_independent(self):
        """Each symbol maintains its own session and portfolio state."""
        tick1 = _make_tick(close=100)
        tick2 = _make_tick(close=200)
        self.session.process_tick("SYM_A", tick1)
        self.session.process_tick("SYM_B", tick2)
        sess_a = self.session.get_or_create_session("SYM_A")
        sess_b = self.session.get_or_create_session("SYM_B")
        assert len(sess_a.data) == 1
        assert len(sess_b.data) == 1
        assert sess_a.data[0].close == 100
        assert sess_b.data[0].close == 200


class TestCommissionSlippagePipeline:
    """Verify commission and slippage across the full position lifecycle."""

    def test_long_open_close_full_accounting(self):
        """LONG: open with slippage, TP close with slippage + commission."""
        portfolio = Portfolio.create_default()
        signal = _make_signal(price=500, sl=480, tp=550)
        pos = portfolio.open_position(signal, "OPTS")
        assert pos is not None
        entry = pos.entry_price
        assert entry == pytest.approx(500 * (1 + SLIPPAGE_PCT), rel=1e-9)
        tick = _make_tick(close=550)
        closed = portfolio.process_tick(tick)
        assert len(closed) == 1
        exit_price = 550 * (1 - SLIPPAGE_PCT)
        gross_pnl = (exit_price - entry) * closed[0].size
        assert closed[0].pnl == pytest.approx(gross_pnl - COMMISSION_PER_LOT, rel=1e-4)

    def test_short_slippage_direction(self):
        """SHORT: entry should be lower (adverse)."""
        portfolio = Portfolio.create_default()
        signal = _make_signal(price=500, sl=520, tp=450, sig_type=SignalType.SELL)
        pos = portfolio.open_position(signal, "OPTS")
        assert pos is not None
        assert pos.entry_price == pytest.approx(500 * (1 - SLIPPAGE_PCT), rel=1e-9)
        assert pos.entry_price < signal.price