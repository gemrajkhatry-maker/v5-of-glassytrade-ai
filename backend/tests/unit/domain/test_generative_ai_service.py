"""Tests for GenerativeAIService — LLM-based entry decision logic."""

from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.domain.fabio_ai.services.prompt_builder import build_entry_prompt, parse_entry_response
from app.domain.ports.llm_inference import ILLMInference


# ---------------------------------------------------------------------------
# Mock LLM adapter
# ---------------------------------------------------------------------------

class MockLLMAdapter(ILLMInference):
    def __init__(self, response=""):
        self._response = response

    def predict(self, instruction, input_text):
        return self._response

    def is_ready(self):
        return True


class FailingLLMAdapter(ILLMInference):
    def predict(self, instruction, input_text):
        raise RuntimeError("Model crashed")

    def is_ready(self):
        return False


def _make_market_data(**overrides):
    base = {
        "ltp": 15100.0,
        "vah": 15200.0,
        "val": 15000.0,
        "poc": 15100.0,
        "delta": 200,
        "volume": 500,
        "market_state": "Balanced",
        "aggression": "Moderate buying",
    }
    base.update(overrides)
    return base


# ===================================================================
# Prompt Building (_build_prompt)
# ===================================================================

class TestBuildPrompt:

    def test_balanced_market(self):
        prompt = build_entry_prompt(_make_market_data(market_state="Balanced"))
        # Price at POC in balanced market → "At POC" or "rotational"
        assert "POC" in prompt or "rotational" in prompt

    def test_trending_market(self):
        # Price outside VA → "trending outside" or "Imbalance. Directional displacement detected."
        prompt = build_entry_prompt(_make_market_data(ltp=15300.0, market_state="Imbalanced"))
        assert "imbalance" in prompt.lower() or "directional" in prompt.lower()

    def test_positive_delta(self):
        prompt = build_entry_prompt(_make_market_data(delta=500))
        assert "+" in prompt or "Buyers" in prompt or "buyers" in prompt.lower()

    def test_negative_delta(self):
        prompt = build_entry_prompt(_make_market_data(delta=-500))
        # Negative delta with default cvd=0 produces aggression 0.00 (neutral)
        assert "aggression score: 0.00" in prompt.lower()

    def test_zero_delta(self):
        prompt = build_entry_prompt(_make_market_data(delta=0))
        # Zero delta with zero cvd_slope shows aggression 0.00 which indicates neutral
        assert "aggression score: 0.00" in prompt.lower()

    def test_price_near_val(self):
        prompt = build_entry_prompt(_make_market_data(ltp=15000.0))
        assert "VAL" in prompt

    def test_price_near_vah(self):
        prompt = build_entry_prompt(_make_market_data(ltp=15200.0, delta=100))
        assert "VAH" in prompt or "Value Area High" in prompt or "broke above" in prompt

    def test_price_at_poc(self):
        prompt = build_entry_prompt(_make_market_data(ltp=15100.0, poc=15100.0))
        assert "POC" in prompt

    def test_all_zero_prices(self):
        prompt = build_entry_prompt(
            {"ltp": 0, "vah": 0, "val": 0, "poc": 0, "delta": 0}
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_volume_bubbles_in_prompt(self):
        prompt = build_entry_prompt(_make_market_data(
            volume_bubbles="BUY bubble at 15100 (500 vol, delta +300)"
        ))
        assert "bubble" in prompt.lower() or "BUBBLE" in prompt

    def test_cvd_divergence_in_prompt(self):
        prompt = build_entry_prompt(_make_market_data(cvd_divergence="BEARISH_DIV"))
        assert "DIVERGENCE" in prompt and "Bearish" in prompt

    def test_prompt_includes_json_response_contract(self):
        prompt = build_entry_prompt(_make_market_data())
        assert "Respond ONLY with a JSON object" in prompt
        # Current schema uses "direction" and "confidence" fields
        assert "direction" in prompt
        assert "MARKET STATE" in prompt




# ===================================================================
# Response Parsing (_parse_response)
# ===================================================================

class TestParseResponse:

    def test_enter_long(self):
        r = parse_entry_response('Trigger: **Enter Long**')
        assert r["direction"] == "LONG"

    def test_enter_short(self):
        r = parse_entry_response('Trigger: **Enter Short**')
        assert r["direction"] == "SHORT"

    def test_trigger_long(self):
        r = parse_entry_response('Trigger: **Long**')
        assert r["direction"] == "LONG"

    def test_trigger_short(self):
        r = parse_entry_response('Trigger: **Short**')
        assert r["direction"] == "SHORT"

    def test_add_to_longs(self):
        r = parse_entry_response('Add to Longs')
        assert r["direction"] == "LONG"

    def test_bank_profit(self):
        r = parse_entry_response('Bank Profit')
        assert r["direction"] == "FLAT"

    def test_walk_away(self):
        r = parse_entry_response('Walk away')
        assert r["direction"] == "FLAT"

    def test_stay_flat(self):
        r = parse_entry_response('Stay Flat')
        assert r["direction"] == "FLAT"

    def test_empty_response(self):
        r = parse_entry_response('')
        assert r["direction"] == "FLAT"

    def test_random_text(self):
        r = parse_entry_response('The quick brown fox jumped over the lazy dog.')
        assert r["direction"] == "FLAT"

    def test_json_response(self):
        r = parse_entry_response(
            '{"direction":"LONG","rationale":"Balance at VAL with buyers stepping in","confidence":"High","market_state":"Balance"}'
        )
        assert r["direction"] == "LONG"
        assert r["confidence"] == "High"

    def test_json_response_with_extra_text(self):
        r = parse_entry_response(
            'Result follows: {"direction":"FLAT","rationale":"No confluence","confidence":"Low","market_state":"Balance"} trailing note'
        )
        assert r["direction"] == "FLAT"
        assert r["confidence"] == "Low"


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

    def test_llm_returns_json_response(self):
        svc = GenerativeAIService(
            MockLLMAdapter(
                '{"direction":"LONG","rationale":"Imbalance with aggressive buying","confidence":"High","market_state":"Imbalance"}'
            )
        )
        result = svc.analyze_market(_make_market_data(market_state="Imbalanced"))
        assert result["direction"] == "LONG"
        assert result["confidence"] == "High"

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
