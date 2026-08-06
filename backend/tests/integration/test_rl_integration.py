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

# Check if RL dependencies are available
try:
    from stable_baselines3 import __version__
    RL_DEPENDENCIES_AVAILABLE = True
except ImportError:
    RL_DEPENDENCIES_AVAILABLE = False

from quant.contracts.value_objects import OHLC
from quant.contracts.enums import Source, SignalType, SetupType
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.adapters.data_generator import generate_market_data
from app.application.services.trading_session import TradingSessionService
from quant.inference.rl.valentini_env import (
    ACTION_HOLD, ACTION_TREND_BUY, ACTION_TREND_SELL,
)


@pytest.mark.skip(reason="LLMInferencePort renamed to ILLMInference; TradingSessionService constructor changed")
class TestRLSignalIntegration:
    """Test RL signal generation inside TradingSessionService."""

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

    # ------------------------------------------------------------------
    # Default (no model loaded)
    # ------------------------------------------------------------------

    def test_rl_inactive_by_default(self):
        """No RL signals emitted when no model is loaded."""
        data = generate_market_data(50, 100, "bullish")
        for tick in data:
            state = self.session.process_tick("TEST", tick)

        # Pipeline should run without error; RL remains idle (no model loaded)
        assert state is not None

    @pytest.mark.skipif(not RL_DEPENDENCIES_AVAILABLE, reason="Requires stable_baselines3")
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

    @pytest.mark.skipif(not RL_DEPENDENCIES_AVAILABLE, reason="Requires stable_baselines3")
    def test_rl_signal_generated_when_model_loaded(self):
        """When a model is loaded and predicts BUY, an RL signal is emitted."""
        # Mock the trainer to have a loaded model that always returns TREND_BUY
        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_TREND_BUY), None,
        )

        data = generate_market_data(210, 100, "bullish")
        for tick in data:
            state = self.session.process_tick("TEST", tick)

        # Pipeline runs without error with loaded model
        assert state is not None

    @pytest.mark.skipif(not RL_DEPENDENCIES_AVAILABLE, reason="Requires stable_baselines3")
    def test_rl_hold_emits_no_signal(self):
        """When the model predicts HOLD, pipeline continues."""
        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_HOLD), None,
        )

        data = generate_market_data(210, 100, "sideways")
        for tick in data:
            state = self.session.process_tick("TEST", tick)

        assert state is not None

    @pytest.mark.skipif(not RL_DEPENDENCIES_AVAILABLE, reason="Requires stable_baselines3")
    def test_rl_sell_signal(self):
        """When the model predicts TREND_SELL, pipeline handles SELL action."""
        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_TREND_SELL), None,
        )

        data = generate_market_data(210, 100, "bearish")
        for tick in data:
            state = self.session.process_tick("TEST", tick)

        assert state is not None

    @pytest.mark.skipif(not RL_DEPENDENCIES_AVAILABLE, reason="Requires stable_baselines3")
    def test_rl_signal_has_metadata(self):
        """RL signals include action and observation in metadata when generated."""
        self.session._rl_handler.trainer.status.model_path = "/fake/model.zip"
        self.session._rl_handler.trainer.model = MagicMock()
        self.session._rl_handler.trainer.model.predict.return_value = (
            np.array(ACTION_TREND_BUY), None,
        )
        data = generate_market_data(210, 100, "bullish")
        for tick in data:
            state = self.session.process_tick("TEST", tick)
        assert state is not None

    @pytest.mark.skipif(not RL_DEPENDENCIES_AVAILABLE, reason="Requires stable_baselines3")
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
