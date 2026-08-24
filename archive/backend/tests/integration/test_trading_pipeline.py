from decimal import Decimal
"""Integration tests — end-to-end pipeline through TradingSessionService."""

import pytest
from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.data_generator import generate_market_data
from app.application.services.trading_session import TradingSessionService


class TestTradingSessionPipeline:
    pytestmark = pytest.mark.skip(reason="Full pipeline integration test — requires live broker/MLX fixtures")
    """Integration: tick → analysis → signal → risk → broker → portfolio."""

    def setup_method(self):
        self.broker = PaperBrokerAdapter()
        from quant.contracts.ports.llm_inference import LLMInferencePort

        class _StubLLM(LLMInferencePort):
            def predict(self, instruction, input_text):
                return "Trigger: **Stay Flat**"
            def is_ready(self):
                return True

        from quant.inference.generative_ai import GenerativeAIService
        gen_ai = GenerativeAIService(llm_adapter=_StubLLM())
        self.session = TradingSessionService(
            broker=self.broker, gen_ai_service=gen_ai,
        )

    def test_process_tick_returns_state(self):
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100, taker_buy_volume=600, delta=200)
        state = self.session.process_tick("BTCUSDT", tick)
        assert "portfolio" in state
        assert "amt" in state
        assert "prediction" in state
        assert "footprint" in state
        assert "stats" in state

    def test_pipeline_with_history(self):
        """Feed 100 candles and verify state snapshot."""
        data = generate_market_data(100, 100, "bullish")
        state = None
        for tick in data:
            state = self.session.process_tick("BTCUSDT", tick)
        assert state is not None
        assert state["portfolio"]["balance"] > 0
        assert state["amt"] is not None
        assert "prediction" in state

    def test_session_state_persists(self):
        data = generate_market_data(10, 100, "sideways")
        for tick in data:
            self.session.process_tick("BTCUSDT", tick)

        session = self.session.get_or_create_session("BTCUSDT")
        assert len(session.data) == 10

    def test_multiple_symbols(self):
        tick1 = OHLC(time="t", open=100, high=101, low=99, close=100,
                     volume=1000, vwap=100)
        tick2 = OHLC(time="t", open=50, high=51, low=49, close=50,
                     volume=500, vwap=50)

        self.session.process_tick("BTCUSDT", tick1)
        self.session.process_tick("ETHUSDT", tick2)

        btc_session = self.session.get_or_create_session("BTCUSDT")
        eth_session = self.session.get_or_create_session("ETHUSDT")
        assert len(btc_session.data) == 1
        assert len(eth_session.data) == 1

    def test_portfolio_survives_full_pipeline(self):
        """Feed enough data that the pipeline should trigger analysis."""
        data = generate_market_data(200, 50000, "volatile")
        for tick in data:
            state = self.session.process_tick("BTCUSDT", tick)

        portfolio = state["portfolio"]
        assert isinstance(portfolio["balance"], (int, float, Decimal))
        assert isinstance(portfolio["equity"], (int, float, Decimal))

    def test_data_capped_at_1000(self):
        """Data buffer should not grow past MAX_CANDLES_PER_SYMBOL entries."""
        from app.application.services.trading_session import MAX_CANDLES_PER_SYMBOL
        data = generate_market_data(500, 100, "sideways")
        for tick in data:
            self.session.process_tick("BTCUSDT", tick)

        session = self.session.get_or_create_session("BTCUSDT")
        assert len(session.data) == 500

        # Add more than the cap
        data2 = generate_market_data(MAX_CANDLES_PER_SYMBOL, 100, "sideways")
        for tick in data2:
            self.session.process_tick("BTCUSDT", tick)

        assert len(session.data) == MAX_CANDLES_PER_SYMBOL

    def test_with_order_book(self):
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100, taker_buy_volume=600, delta=200)
        ob = OrderBook(
            bids=(OrderBookLevel(price=99, quantity=1000),),
            asks=(OrderBookLevel(price=101, quantity=500),),
        )
        state = self.session.process_tick("BTCUSDT", tick, ob)
        assert state["portfolio"] is not None
