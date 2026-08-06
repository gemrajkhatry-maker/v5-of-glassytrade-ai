"""PHASE 2 — BACKEND PIPELINE (INTEGRATION).

Feeds deterministic synthetic OHLC ticks through the REAL
``TradingSessionService.process_tick`` pipeline (the same code path the
gameloop WebSocket and the stream manager use).  Asserts:
  - Indicators / candle buffer update (session.data grows)
  - AMT analysis emits (session.last_amt populated, snapshot contains amt)
  - OMS lifecycle: a position opened via the real PaperBrokerAdapter is
    closed by the pipeline when a tick breaches its stop
  - No silent failures (exceptions would fail the test)

No network is touched: PaperBrokerAdapter is the real in-process adapter and
the probability engine is the real NoOp adapter (paper mode).
"""
from __future__ import annotations

import pytest
from decimal import Decimal

from app.infrastructure.adapters.data_generator import generate_market_data
from app.application.services.trading_session import TradingSessionService
from quant.contracts.ports.probability_inference import NoOpProbabilityAdapter
from quant.contracts.entities import Signal
from quant.contracts.enums import SignalType, SetupType, Source, PositionStatus
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter


class _StubGenAI:
    """Minimal GenerativeAI stub: is_ready()=False keeps the real LLM path off."""

    def is_ready(self) -> bool:
        return False

    def analyze_market(self, *args, **kwargs):
        return {"direction": "FLAT", "confidence": "Low", "rationale": "stub"}


def _make_service():
    return TradingSessionService(
        broker=PaperBrokerAdapter(),
        gen_ai_service=_StubGenAI(),
        storage=None,
        probability_engine=NoOpProbabilityAdapter(),
        allow_short=False,
    )


SYMBOL = "CRUDEOIL 17 AUG 7200 CALL"


class TestPipelineIngestion:
    def test_ticks_update_session_data_and_snapshot(self):
        service = _make_service()
        try:
            candles = generate_market_data(days=40, start_price=100.0, regime="sideways")
            session = service.get_or_create_session(SYMBOL)
            service.set_symbol_trading_state(SYMBOL, "TRADABLE")

            for i, c in enumerate(candles):
                snapshot = service.process_tick(SYMBOL, c)
                assert isinstance(snapshot, dict)
                assert len(session.data) == i + 1  # every tick lands in the buffer
                assert snapshot != {}

            # AMT analysis must have emitted at least one result over 40 candles
            assert session.last_amt is not None
            assert len(session.data) == len(candles)
        finally:
            service.cleanup()

    def test_pipeline_closes_position_on_stop_breach(self):
        """Real OMS path inside the pipeline: open via paper broker, then a
        stop-breaching tick must close it with reason STOP_LOSS."""
        service = _make_service()
        try:
            session = service.get_or_create_session(SYMBOL)
            service.set_symbol_trading_state(SYMBOL, "TRADABLE")
            # warm up the session so the pipeline tolerates the position
            for c in generate_market_data(days=15, start_price=100.0, regime="sideways"):
                service.process_tick(SYMBOL, c)
            sig = Signal(
                type=SignalType.BUY, price=Decimal("100"), reason="phase2",
                stop_loss=Decimal("95"), take_profit=Decimal("120"),
                timestamp="2026-08-05T09:30:00Z", setup=SetupType.TREND_MODEL,
                source=Source.AMT,
            )
            pos = service._broker.execute_order(sig, session.portfolio, SYMBOL)
            assert pos is not None
            assert pos in session.portfolio.positions
            open_before = len(session.portfolio.positions)

            # Stop breach tick (low=93 < SL=95)
            tick = generate_market_data(days=1, start_price=93.0, regime="sideways")[0]
            tick = tick.__class__.create(
                tick.time, 93.0, 94.0, 92.0, 93.2, 800, vwap=93.0,
            )
            service.process_tick(SYMBOL, tick)

            assert len(session.portfolio.positions) == open_before - 1
            assert pos.status == PositionStatus.CLOSED
            assert pos.close_reason == "STOP_LOSS"
            assert any(t.id == pos.id for t in session.portfolio.closed_trades)
        finally:
            service.cleanup()

    def test_multi_symbol_isolation(self):
        """Two symbols fed through the same service must not share candle state."""
        service = _make_service()
        try:
            a = generate_market_data(days=10, start_price=100.0, regime="bullish")
            b = generate_market_data(days=10, start_price=50.0, regime="bearish")
            service.set_symbol_trading_state("SYM_A", "TRADABLE")
            service.set_symbol_trading_state("SYM_B", "TRADABLE")
            for c in a:
                service.process_tick("SYM_A", c)
            for c in b:
                service.process_tick("SYM_B", c)

            sa = service.get_or_create_session("SYM_A")
            sb = service.get_or_create_session("SYM_B")
            assert len(sa.data) == 10
            assert len(sb.data) == 10
            assert sa.data[-1].close > sa.data[0].open      # A: bullish
            assert sb.data[-1].close < sb.data[0].open      # B: bearish
            assert sa.data is not sb.data
        finally:
            service.cleanup()
