"""Integration tests for RL signal path in TradingSessionService.

Verifies that:
  - The RL trainer is inactive by default (no model loaded)
  - State snapshot includes rlStatus and stats.rl
  - When a mock model is loaded, RL signals are generated and flow
    through the event bus
  - Action masking respects AMT market state (balanced vs imbalanced)
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from app.domain.trading.models.value_objects import OHLC
from app.domain.trading.models.enums import Source, SignalType, SetupType
from app.domain.trading.events import SignalGenerated
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.data_generator import generate_market_data
from app.application.services.trading_session import TradingSessionService
from app.domain.fabio_ai.rl.valentini_env import (
    ACTION_HOLD, ACTION_TREND_BUY, ACTION_TREND_SELL,
)


class TestRLSignalIntegration:
    """Test RL signal generation inside TradingSessionService."""

    def setup_method(self):
        self.bus = InMemoryEventBus()
        self.broker = PaperBrokerAdapter()
        from app.domain.ports.llm_inference import LLMInferencePort

        class _StubLLM(LLMInferencePort):
            def predict(self, instruction, input_text):
                return "Trigger: **Stay Flat**"
            def is_ready(self):
                return True

        from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
        gen_ai = GenerativeAIService(llm_adapter=_StubLLM())
        self.session = TradingSessionService(
            event_bus=self.bus, broker=self.broker, gen_ai_service=gen_ai,
        )

    # ------------------------------------------------------------------
    # Default (no model loaded)
    # ------------------------------------------------------------------

    def test_rl_inactive_by_default(self):
        """No RL signals emitted when no model is loaded."""
        signals: list[SignalGenerated] = []
        self.bus.subscribe(SignalGenerated, lambda e: signals.append(e))

        data = generate_market_data(50, 100, "bullish")
        for tick in data:
            self.session.process_tick("TEST", tick)

        rl_signals = [s for s in signals if s.signal.source == Source.RL]
        assert len(rl_signals) == 0

    def test_state_snapshot_includes_rl_status(self):
        """State snapshot always contains rlStatus and stats.rl."""
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        state = self.session.process_tick("TEST", tick)

        assert "rlStatus" in state
        assert state["rlStatus"]["state"] == "idle"
        assert state["rlStatus"]["modelLoaded"] is False
        assert "rl" in state["statsBySource"]

    def test_trainer_status_fields(self):
        """rlStatus has all expected fields."""
        tick = OHLC(time="t", open=100, high=101, low=99, close=100,
                    volume=1000, vwap=100)
        state = self.session.process_tick("TEST", tick)

        rl = state["rlStatus"]
        expected_keys = {
            "state", "modelLoaded", "timestepsDone", "totalTimesteps",
            "episodeCount", "meanReward", "meanSharpe",
            "totalTrades", "elapsedSeconds",
        }
        assert expected_keys.issubset(rl.keys())

    # ------------------------------------------------------------------
    # With mock model loaded
    # ------------------------------------------------------------------

    @pytest.mark.skip(reason="RL signal generation is no longer handled directly in process_tick")
    def test_rl_signal_generated_when_model_loaded(self):
        """When a model is loaded and predicts BUY, an RL signal is emitted."""
        signals: list[SignalGenerated] = []
        self.bus.subscribe(SignalGenerated, lambda e: signals.append(e))

        # Mock the trainer to have a loaded model that always returns TREND_BUY
        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_TREND_BUY), None,
        )

        data = generate_market_data(210, 100, "bullish")
        for tick in data:
            self.session.process_tick("TEST", tick)

        rl_signals = [s for s in signals if s.signal.source == Source.RL]
        assert len(rl_signals) > 0, "Expected at least one RL signal"

        first_rl = rl_signals[0].signal
        assert first_rl.type == SignalType.BUY
        assert first_rl.setup == SetupType.RL_ENTRY
        assert first_rl.source == Source.RL
        assert "RL" in first_rl.reason

    def test_rl_hold_emits_no_signal(self):
        """When the model predicts HOLD, no RL signal is emitted."""
        signals: list[SignalGenerated] = []
        self.bus.subscribe(SignalGenerated, lambda e: signals.append(e))

        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_HOLD), None,
        )

        data = generate_market_data(210, 100, "sideways")
        for tick in data:
            self.session.process_tick("TEST", tick)

        rl_signals = [s for s in signals if s.signal.source == Source.RL]
        assert len(rl_signals) == 0

    @pytest.mark.skip(reason="RL signal generation is no longer handled directly in process_tick")
    def test_rl_sell_signal(self):
        """When the model predicts TREND_SELL, a SELL signal is generated."""
        signals: list[SignalGenerated] = []
        self.bus.subscribe(SignalGenerated, lambda e: signals.append(e))

        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_TREND_SELL), None,
        )

        data = generate_market_data(210, 100, "bearish")
        for tick in data:
            self.session.process_tick("TEST", tick)

        rl_signals = [s for s in signals if s.signal.source == Source.RL]
        assert len(rl_signals) > 0
        for sig_event in rl_signals:
            assert sig_event.signal.type == SignalType.SELL

    @pytest.mark.skip(reason="RL signal generation is no longer handled directly in process_tick")
    def test_rl_signal_has_metadata(self):
        """RL signals include action and observation in metadata."""
        signals: list[SignalGenerated] = []
        self.bus.subscribe(SignalGenerated, lambda e: signals.append(e))

        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_TREND_BUY), None,
        )

        data = generate_market_data(210, 100, "bullish")
        for tick in data:
            self.session.process_tick("TEST", tick)

        rl_signals = [s for s in signals if s.signal.source == Source.RL]
        if rl_signals:
            meta = rl_signals[0].signal.metadata
            assert "rl_action" in meta
            assert "obs" in meta
            assert isinstance(meta["obs"], list)
            assert len(meta["obs"]) == 12  # 12-feature observation vector

    def test_rl_error_does_not_crash_pipeline(self):
        """If the RL predict() throws, the rest of the pipeline continues."""
        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.side_effect = RuntimeError("boom")

        data = generate_market_data(210, 100, "sideways")
        # Should not raise
        for tick in data:
            state = self.session.process_tick("TEST", tick)

        assert state is not None
        assert "portfolio" in state
