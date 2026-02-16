"""Tests for GenerativeAIService — LLM-based entry decision logic."""

import pytest

from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.ports.llm_inference import LLMInferencePort


# ---------------------------------------------------------------------------
# Mock LLM adapter
# ---------------------------------------------------------------------------

class MockLLMAdapter(LLMInferencePort):
    def __init__(self, response=""):
        self._response = response

    def predict(self, instruction, input_text):
        return self._response

    def is_ready(self):
        return True


class FailingLLMAdapter(LLMInferencePort):
    def predict(self, instruction, input_text):
        raise RuntimeError("Model crashed")

    def is_ready(self):
        return False


@pytest.fixture
def svc() -> GenerativeAIService:
    return GenerativeAIService(MockLLMAdapter())


def _make_market_data(**overrides):
    base = {
        "ltp": 15100.0,
        "vah": 15200.0,
        "val": 15000.0,
        "poc": 15100.0,
        "delta": 200,
        "market_state": "Balanced",
        "aggression": "Moderate buying",
    }
    base.update(overrides)
    return base


# ===================================================================
# Prompt Building (_build_prompt)
# ===================================================================

class TestBuildPrompt:

    def test_balanced_market(self, svc):
        prompt = svc._build_prompt(_make_market_data(market_state="Balanced"))
        assert "inside the Value Area" in prompt

    def test_trending_market(self, svc):
        prompt = svc._build_prompt(_make_market_data(market_state="Imbalanced"))
        assert "outside the Value Area" in prompt

    def test_positive_delta(self, svc):
        prompt = svc._build_prompt(_make_market_data(delta=500))
        assert "Buyers are aggressive" in prompt

    def test_negative_delta(self, svc):
        prompt = svc._build_prompt(_make_market_data(delta=-500))
        assert "Sellers are aggressive" in prompt

    def test_zero_delta(self, svc):
        prompt = svc._build_prompt(_make_market_data(delta=0))
        assert "neutral" in prompt

    def test_price_near_val(self, svc):
        prompt = svc._build_prompt(_make_market_data(ltp=15000.0))
        assert "testing Value Area Low" in prompt

    def test_price_near_vah(self, svc):
        prompt = svc._build_prompt(_make_market_data(ltp=15200.0))
        assert "testing Value Area High" in prompt

    def test_price_at_poc(self, svc):
        # Price very close to POC (within 0.2%)
        prompt = svc._build_prompt(_make_market_data(ltp=15100.0, poc=15100.0))
        assert "Point of Control" in prompt

    def test_all_zero_prices(self, svc):
        prompt = svc._build_prompt(
            {"ltp": 0, "vah": 0, "val": 0, "poc": 0, "delta": 0}
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ===================================================================
# Response Parsing (_parse_response)
# ===================================================================

class TestParseResponse:

    def test_enter_long(self, svc):
        r = svc._parse_response('Trigger: **Enter Long**')
        assert r["direction"] == "LONG"

    def test_enter_short(self, svc):
        r = svc._parse_response('Trigger: **Enter Short**')
        assert r["direction"] == "SHORT"

    def test_trigger_long(self, svc):
        r = svc._parse_response('Trigger: **Long**')
        assert r["direction"] == "LONG"

    def test_trigger_short(self, svc):
        r = svc._parse_response('Trigger: **Short**')
        assert r["direction"] == "SHORT"

    def test_add_to_longs(self, svc):
        r = svc._parse_response('Add to Longs')
        assert r["direction"] == "LONG"

    def test_bank_profit(self, svc):
        r = svc._parse_response('Bank Profit')
        assert r["direction"] == "FLAT"

    def test_walk_away(self, svc):
        r = svc._parse_response('Walk away')
        assert r["direction"] == "FLAT"

    def test_stay_flat(self, svc):
        r = svc._parse_response('Stay Flat')
        assert r["direction"] == "FLAT"

    def test_empty_response(self, svc):
        r = svc._parse_response('')
        assert r["direction"] == "FLAT"

    def test_random_text(self, svc):
        r = svc._parse_response('The quick brown fox jumped over the lazy dog.')
        assert r["direction"] == "FLAT"


# ===================================================================
# Full analyze_market flow
# ===================================================================

class TestAnalyzeMarket:

    def test_llm_returns_enter_long(self):
        svc = GenerativeAIService(MockLLMAdapter("Trigger: **Enter Long**"))
        result = svc.analyze_market(_make_market_data())
        assert result["direction"] == "LONG"

    def test_llm_returns_stay_flat(self):
        svc = GenerativeAIService(MockLLMAdapter("Stay Flat"))
        result = svc.analyze_market(_make_market_data())
        assert result["direction"] == "FLAT"

    def test_llm_raises_exception(self):
        svc = GenerativeAIService(FailingLLMAdapter())
        result = svc.analyze_market(_make_market_data())
        assert result["direction"] == "FLAT"
        assert "Error" in result["rationale"]

    def test_all_zero_market_data(self):
        svc = GenerativeAIService(MockLLMAdapter("Stay Flat"))
        result = svc.analyze_market(
            {"ltp": 0, "vah": 0, "val": 0, "poc": 0, "delta": 0}
        )
        assert result["direction"] == "FLAT"
