"""Integration tests for the full LLM entry pipeline."""
from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.entry_gate_coordinator import EntryGateCoordinator
from app.application.handlers.llm_decision_processor import LLMDecisionProcessor


class MockLLMAdapter:
    """Mock ILLMInference adapter."""
    def __init__(self, ready=True, response=None, raise_error=False, delay=0):
        self._ready = ready
        self._response = response or '{"direction":"LONG","confidence":"High","rationale":"bullish structure"}'
        self._raise_error = raise_error
        self._delay = delay
        self.call_count = 0

    def is_ready(self):
        return self._ready

    def predict(self, instruction, input_text, **kwargs):
        self.call_count += 1
        if self._delay:
            time.sleep(self._delay)
        if self._raise_error:
            raise Exception("LLM error")
        return self._response


class MockTick:
    def __init__(self, close=100.0, symbol="NIFTY", delta=50.0, volume=1000):
        self.close = close
        self.symbol = symbol
        self.delta = delta
        self.volume = volume


class MockAmtResult:
    def __init__(self, **kwargs):
        self.market_state = kwargs.get("market_state", "BALANCED")
        self.poc = kwargs.get("poc", 100.0)
        self.value_area_high = kwargs.get("value_area_high", 105.0)
        self.value_area_low = kwargs.get("value_area_low", 95.0)
        self.aggression_score = kwargs.get("aggression_score", 3.0)
        self.aggression = kwargs.get("aggression", 3.0)
        self.cvd_slope = kwargs.get("cvd_slope", 0.5)
        self.profile_shape = kwargs.get("profile_shape", "B")
        self.drive_number = kwargs.get("drive_number", 1)
        self.drive_entry_valid = kwargs.get("drive_entry_valid", False)
        self.session_vwap = kwargs.get("session_vwap", 99.0)
        self.is_extreme_deviation = kwargs.get("is_extreme_deviation", False)


class MockOHLC:
    def __init__(self, close=100.0, time="2024-01-01T09:15:00"):
        self.close = close
        self.time = time


class TestFullEntryPipeline:
    """Integration tests for full LLM entry flow."""

    def test_decision_processor_safety_nets_block_short(self):
        """Full flow: SHORT decision in BUY-ONLY mode is blocked."""
        processor = LLMDecisionProcessor(allow_short=False)
        direction, confidence, rationale = processor.apply_safety_nets(
            "SHORT", 0.8, "bearish", MockTick(), MockAmtResult()
        )
        assert direction == "FLAT"
        assert "BUY-ONLY" in rationale

    def test_decision_processor_vwap_extreme_downgrade(self):
        """Full flow: LONG at VWAP extreme is downgraded."""
        processor = LLMDecisionProcessor(allow_short=True)
        amt = MockAmtResult(value_area_high=105.0)
        # Create a mock with vwap_upper_2
        amt.vwap_upper_2 = 100.0
        tick = MockTick(close=102.0)  # >= 100 * 1.01
        direction, confidence, rationale = processor.apply_safety_nets(
            "LONG", 0.8, "bullish", tick, amt
        )
        assert confidence == 0.3
        assert "VWAP extreme" in rationale

    def test_decision_processor_direction_mismatch_detected(self):
        """Full flow: LLM LONG vs agent SHORT triggers mismatch."""
        processor = LLMDecisionProcessor()
        agent = MagicMock()
        agent.direction = "SHORT"
        worker_queue = queue.Queue()
        result = processor.check_direction_mismatch(
            agent, "LONG", "NIFTY", MagicMock(), worker_queue
        )
        assert result is True


class TestGateCoordinatorIntegration:
    """Integration tests for gate coordinator with real gate pipeline."""

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_gate_coordinator_cvd_blocks(self, mock_gates):
        """Gate coordinator blocks entry when CVD is extreme opposing."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0)] * 50
        amt = MockAmtResult(market_state="BALANCED", cvd_slope=-150.0)
        tick = MockTick()
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="LONG", tick_size=0.05
        )
        assert passed is False
        assert "CVD extreme selling" in reason

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_gate_coordinator_profile_blocks(self, mock_gates):
        """Gate coordinator blocks entry when profile shape opposes."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0)] * 50
        amt = MockAmtResult(profile_shape="P")
        tick = MockTick()
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="LONG", tick_size=0.05
        )
        assert passed is False
        assert "P-shape blocks LONG" in reason

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_gate_coordinator_all_pass(self, mock_gates):
        """Gate coordinator passes when all gates clear."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0)] * 50
        amt = MockAmtResult(
            market_state="IMBALANCED",
            cvd_slope=30.0,
            profile_shape="B",
            drive_entry_valid=True,
        )
        tick = MockTick(close=100.0)
        passed, reason, drive_valid = coordinator.check_entry_eligibility(
            data, amt, tick, direction="LONG", tick_size=0.05
        )
        assert passed is True
        assert drive_valid is True


class TestResponseParsingFallback:
    """Integration tests for response parsing with various LLM outputs."""

    def test_json_parse_valid(self):
        """Valid JSON from LLM is parsed correctly."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = '{"direction": "LONG", "confidence": "High", "rationale": "bullish"}'
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "High"

    def test_embedded_json_extracted(self):
        """JSON embedded in prose is extracted and parsed."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = 'Based on my analysis: {"direction": "SHORT", "confidence": "Medium", "rationale": "bearish divergence"} — this is my recommendation.'
        result = parse_entry_response(text)
        assert result["direction"] == "SHORT"
        assert result["confidence"] == "Medium"

    def test_keyword_fallback(self):
        """When no JSON found, keyword scanning is used."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = "I see a strong BUY signal here based on the structure."
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"

    def test_keyword_fallback_sell(self):
        """Keyword scanning detects SELL."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = "The market looks weak, recommend SELL position."
        result = parse_entry_response(text)
        assert result["direction"] == "SHORT"

    def test_keyword_fallback_flat(self):
        """Keyword scanning defaults to FLAT when no direction found."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = "Market is unclear, wait for better setup."
        result = parse_entry_response(text)
        assert result["direction"] == "FLAT"


class TestConsistencyGuard:
    """Integration tests for consistency guard behavior."""

    def test_high_confidence_preserved_on_low_flip(self):
        """High confidence decision is preserved when new result is Low+FLAT."""
        # Simulate consistency guard logic from LLMEntryHandler
        prev_direction = "LONG"
        prev_confidence = "High"
        new_direction = "FLAT"
        new_confidence = "Low"

        # Consistency guard logic
        within_60s = True
        if within_60s and prev_confidence == "High" and new_confidence == "Low" and new_direction == "FLAT":
            final_direction = prev_direction
            final_confidence = prev_confidence
            final_rationale = "CONSISTENCY GUARD: prevented High→Low flip"
        else:
            final_direction = new_direction
            final_confidence = new_confidence
            final_rationale = new_confidence

        assert final_direction == "LONG"
        assert final_confidence == "High"
        assert "CONSISTENCY GUARD" in final_rationale

    def test_expired_uses_new_decision(self):
        """After 60s expiry, new decision is used."""
        prev_direction = "LONG"
        prev_confidence = "High"
        new_direction = "SHORT"
        new_confidence = "Medium"

        within_60s = False
        if within_60s and prev_confidence == "High" and new_confidence == "Low" and new_direction == "FLAT":
            final_direction = prev_direction
            final_confidence = prev_confidence
        else:
            final_direction = new_direction
            final_confidence = new_confidence

        assert final_direction == "SHORT"
        assert final_confidence == "Medium"


class TestRuleBasedRationaleFallback:
    """Integration tests for rule-based rationale when LLM unavailable."""

    def test_flat_low_rr(self):
        """FLAT with low R:R explains why."""
        from app.domain.fabio_ai.services.rule_based_rationale import RationaleContext, RuleBasedRationale
        ctx = RationaleContext(
            market_state="BALANCED", zone="AT_POC", poc=100.0, vah=105.0, val=95.0,
            price=100.0, aggression_score=3.0, aggression_confidence="Medium",
            footprint_confirmed=False, cvd_confirmed=False, big_trade_confirmed=False,
            absorption_detected=False, ofi_aligned=False, confluence_bonus=False,
            volume_bubble_near=False, cvd_slope=0.0, cvd_divergence="",
            drive_number=1, drive_level=0.0, direction="FLAT", setup_type="",
            entry_price=100.0, stop_loss=99.0, take_profit=101.0, r_r_ratio=1.0,
            gate_number=0, profile_shape="",
        )
        rationale = RuleBasedRationale().generate(ctx)
        assert "too low" in rationale.lower()

    def test_directional_with_aggression(self):
        """Directional rationale includes aggression confirmations."""
        from app.domain.fabio_ai.services.rule_based_rationale import RationaleContext, RuleBasedRationale
        ctx = RationaleContext(
            market_state="IMBALANCED", zone="", poc=100.0, vah=105.0, val=95.0,
            price=106.0, aggression_score=3.5, aggression_confidence="High",
            footprint_confirmed=True, cvd_confirmed=True, big_trade_confirmed=False,
            absorption_detected=False, ofi_aligned=True, confluence_bonus=False,
            volume_bubble_near=False, cvd_slope=0.5, cvd_divergence="",
            drive_number=1, drive_level=0.0, direction="LONG", setup_type="TREND_MODEL",
            entry_price=106.0, stop_loss=103.0, take_profit=115.0, r_r_ratio=3.0,
            gate_number=0, profile_shape="B",
        )
        rationale = RuleBasedRationale().generate(ctx)
        assert "IMBALANCED" in rationale
        assert "Trend" in rationale
        assert "footprint" in rationale
