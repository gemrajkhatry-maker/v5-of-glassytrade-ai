"""Tests for RegimeDetector — triggers LLM on regime changes, not timer."""

import time
from unittest.mock import patch

import pytest

from app.domain.fabio_ai.services.regime_detector import RegimeDetector
from app.domain.trading.models.value_objects import AMTResult, OHLC


def _tick(close=100.0, delta=50.0, volume=1000.0, t="2024-01-01T10:00:00Z") -> OHLC:
    return OHLC(open=close, high=close + 1, low=close - 1, close=close,
                volume=volume, time=t, delta=delta)


def _amt(poc=100.0, vah=105.0, val=95.0, state="BALANCED") -> AMTResult:
    return AMTResult(market_state=state, poc=poc, value_area_high=vah,
                     value_area_low=val)


class TestRegimeDetector:
    def setup_method(self):
        self.rd = RegimeDetector()

    def test_first_call_always_triggers(self):
        assert self.rd.should_trigger_llm(_tick(), _amt()) is True

    def test_no_trigger_within_cooldown(self):
        self.rd.should_trigger_llm(_tick(), _amt())
        # Immediately after — should not trigger even with state change
        assert self.rd.should_trigger_llm(_tick(), _amt(state="IMBALANCED")) is False

    @patch("app.domain.fabio_ai.services.regime_detector.time")
    def test_triggers_on_state_change(self, mock_time):
        mock_time.time.return_value = 100.0
        self.rd.should_trigger_llm(_tick(), _amt())

        mock_time.time.return_value = 106.0  # past cooldown
        assert self.rd.should_trigger_llm(_tick(), _amt(state="IMBALANCED")) is True

    @patch("app.domain.fabio_ai.services.regime_detector.time")
    def test_triggers_on_zone_change(self, mock_time):
        mock_time.time.return_value = 100.0
        self.rd.should_trigger_llm(_tick(close=100), _amt(poc=100, vah=105, val=95))

        mock_time.time.return_value = 106.0
        # Price moves from INSIDE_VA to ABOVE_VAH
        assert self.rd.should_trigger_llm(_tick(close=105), _amt(poc=100, vah=105, val=95)) is True

    @patch("app.domain.fabio_ai.services.regime_detector.time")
    def test_triggers_on_poc_migration(self, mock_time):
        mock_time.time.return_value = 100.0
        self.rd.should_trigger_llm(_tick(), _amt(poc=100))

        mock_time.time.return_value = 106.0
        # POC moves by 0.5% (> 0.2% threshold)
        assert self.rd.should_trigger_llm(_tick(), _amt(poc=100.5)) is True

    @patch("app.domain.fabio_ai.services.regime_detector.time")
    def test_no_trigger_without_change(self, mock_time):
        mock_time.time.return_value = 100.0
        self.rd.should_trigger_llm(_tick(), _amt())

        mock_time.time.return_value = 106.0
        # Same state — no trigger
        assert self.rd.should_trigger_llm(_tick(), _amt()) is False

    @patch("app.domain.fabio_ai.services.regime_detector.time")
    def test_triggers_on_delta_spike(self, mock_time):
        mock_time.time.return_value = 100.0
        self.rd.should_trigger_llm(_tick(delta=50), _amt())

        # Build up delta history with normal values
        for i in range(6):
            mock_time.time.return_value = 100.0  # within cooldown, won't trigger but records deltas
            self.rd.should_trigger_llm(_tick(delta=50), _amt())

        mock_time.time.return_value = 200.0  # past cooldown
        # Massive delta spike (3x+ average)
        result = self.rd.should_trigger_llm(_tick(delta=200), _amt())
        assert result is True
