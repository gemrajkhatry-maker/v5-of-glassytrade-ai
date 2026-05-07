"""Tests for GenerativeAIService."""
import pytest
from unittest.mock import MagicMock

from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService

_DEFAULT_MOCK_RESPONSE = '{"direction": "LONG", "confidence": "High", "rationale": "test"}'
_UNSET = object()


class MockLLMAdapter:
    """Mock ILLMInference adapter for testing."""

    def __init__(self, ready=True, response=_UNSET, raise_error=False):
        self._ready = ready
        self._response = _DEFAULT_MOCK_RESPONSE if response is _UNSET else response
        self._raise_error = raise_error
        self.call_count = 0

    def is_ready(self):
        return self._ready

    def predict(self, instruction, input_text, **kwargs):
        self.call_count += 1
        if self._raise_error:
            raise Exception("LLM error")
        return self._response


class TestAnalyzeMarket:
    """Tests for GenerativeAIService.analyze_market()."""

    def _make_market_data(self, **overrides):
        data = {
            "ltp": 100.0,
            "poc": 99.0,
            "vah": 102.0,
            "val": 98.0,
            "market_state": "BALANCED",
            "aggression": 0.5,
            "delta": 10.0,
            "cvd_slope": 0.3,
        }
        data.update(overrides)
        return data

    def test_successful_llm_analysis_returns_parsed_decision(self):
        """When LLM returns valid JSON, analyze_market parses and returns it."""
        adapter = MockLLMAdapter(
            response='{"direction": "SHORT", "confidence": "Medium", "rationale": "bearish structure"}'
        )
        service = GenerativeAIService(llm_adapter=adapter)
        result = service.analyze_market(self._make_market_data())

        assert result["direction"] == "SHORT"
        assert result["confidence"] == "Medium"
        assert "bearish structure" in result["rationale"]
        assert "input_prompt" in result
        assert result["market_state"] == "BALANCED"
        assert result["aggression"] == 0.5
        assert adapter.call_count == 1

    def test_successful_llm_analysis_normalizes_invalid_confidence(self):
        """Non-JSON responses are parsed by the keyword fallback, which normalizes confidence."""
        # Non-JSON text triggers the keyword fallback parser
        adapter = MockLLMAdapter(
            response="LONG with 75% confidence based on structure"
        )
        service = GenerativeAIService(llm_adapter=adapter)
        result = service.analyze_market(self._make_market_data())

        assert result["direction"] == "LONG"
        # Keyword parser formats confidence as percentage: "75%"
        assert result["confidence"] == "75%"

    def test_llm_failure_falls_back_to_flat(self):
        """When LLM predict raises an exception, fallback to FLAT direction."""
        adapter = MockLLMAdapter(raise_error=True)
        service = GenerativeAIService(llm_adapter=adapter)
        result = service.analyze_market(self._make_market_data())

        assert result["direction"] == "FLAT"
        assert result["confidence"] == "Low"
        assert "Error" in result["rationale"]
        assert adapter.call_count == 1

    def test_llm_returns_none_falls_back_to_flat(self):
        """When LLM returns None, fallback to FLAT direction."""
        adapter = MockLLMAdapter(response=None)
        service = GenerativeAIService(llm_adapter=adapter)
        result = service.analyze_market(self._make_market_data())

        assert result["direction"] == "FLAT"
        assert result["confidence"] == "Low"
        assert "None" in result["rationale"]

    def test_cache_hit_returns_cached_result(self):
        """Same market_data produces same prompt hash and returns cached result."""
        adapter = MockLLMAdapter(
            response='{"direction": "LONG", "confidence": "High", "rationale": "cached"}'
        )
        service = GenerativeAIService(llm_adapter=adapter)
        market_data = self._make_market_data()

        result1 = service.analyze_market(market_data)
        result2 = service.analyze_market(market_data)

        # Both results should be identical (cache hit on second call)
        assert result1 is result2
        # LLM should only be called once
        assert adapter.call_count == 1

    def test_cache_miss_calls_llm(self):
        """Different market_data produces different prompt hash and calls LLM again."""
        adapter = MockLLMAdapter(
            response='{"direction": "LONG", "confidence": "High", "rationale": "fresh"}'
        )
        service = GenerativeAIService(llm_adapter=adapter)

        result1 = service.analyze_market(self._make_market_data(ltp=100.0))
        result2 = service.analyze_market(self._make_market_data(ltp=200.0))

        # Results should be different objects (cache miss)
        assert result1 is not result2
        # LLM should be called twice
        assert adapter.call_count == 2

    def test_cache_evicts_oldest_entry_when_full(self):
        """Cache evicts oldest entry when exceeding max size (8)."""
        adapter = MockLLMAdapter(
            response='{"direction": "LONG", "confidence": "High", "rationale": "evict test"}'
        )
        service = GenerativeAIService(llm_adapter=adapter)

        # Fill cache with 8 unique entries
        for i in range(8):
            service.analyze_market(self._make_market_data(ltp=float(i)))

        assert adapter.call_count == 8
        assert len(service._cache) == 8

        # 9th unique entry should evict the oldest
        service.analyze_market(self._make_market_data(ltp=999.0))
        assert adapter.call_count == 9
        assert len(service._cache) == 8

    def test_analyze_market_preserves_market_state_and_aggression(self):
        """Result includes market_state and aggression from input data."""
        adapter = MockLLMAdapter(
            response='{"direction": "FLAT", "confidence": "Low", "rationale": "no edge"}'
        )
        service = GenerativeAIService(llm_adapter=adapter)
        data = self._make_market_data(
            market_state="IMBALANCED",
            aggression=0.9,
        )
        result = service.analyze_market(data)

        assert result["market_state"] == "IMBALANCED"
        assert result["aggression"] == 0.9


class TestIsReady:
    """Tests for GenerativeAIService.is_ready()."""

    def test_ready_when_llm_adapter_is_ready(self):
        """is_ready returns True when the underlying adapter is ready."""
        adapter = MockLLMAdapter(ready=True)
        service = GenerativeAIService(llm_adapter=adapter)
        assert service.is_ready() is True

    def test_not_ready_when_adapter_not_ready(self):
        """is_ready returns False when the underlying adapter is not ready."""
        adapter = MockLLMAdapter(ready=False)
        service = GenerativeAIService(llm_adapter=adapter)
        assert service.is_ready() is False


class TestRuntimeState:
    """Tests for GenerativeAIService.runtime_state()."""

    def test_returns_state_dict_with_model_info(self):
        """runtime_state returns a dict containing model/adapter state info."""
        adapter = MockLLMAdapter(ready=True)
        # Attach a runtime_state method to the mock
        adapter.runtime_state = MagicMock(return_value={"state": "READY", "model": "test-model"})
        service = GenerativeAIService(llm_adapter=adapter)

        state = service.runtime_state()

        assert isinstance(state, dict)
        assert state["state"] == "READY"
        assert state["model"] == "test-model"

    def test_returns_unknown_when_adapter_has_no_runtime_state(self):
        """When adapter lacks runtime_state, returns UNKNOWN state."""
        adapter = MockLLMAdapter(ready=True)
        # Don't attach runtime_state method
        service = GenerativeAIService(llm_adapter=adapter)

        state = service.runtime_state()

        assert state["state"] == "UNKNOWN"
        assert "runtime_state not implemented" in state["reason"]
