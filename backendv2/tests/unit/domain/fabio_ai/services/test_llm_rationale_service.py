"""Tests for llm_rationale_service.py — async rationale generation."""
from __future__ import annotations

import asyncio

import pytest

from app.domain.fabio_ai.services.llm_rationale_service import (
    LLMRationaleService,
    RationaleResult,
)


class TestGenerateRationale:
    """Tests for generate_rationale()."""

    @pytest.mark.asyncio
    async def test_deterministic_fallback_when_no_predict_fn(self):
        """When predict=None, returns deterministic fallback message."""
        service = LLMRationaleService(llm_predict_fn=None)
        result = await service.generate_rationale({})
        assert isinstance(result, RationaleResult)
        assert result.success is True
        assert "deterministic pipeline" in result.text

    @pytest.mark.asyncio
    async def test_llm_path_returns_rationale_with_success(self):
        """When LLM predict works, returns rationale with success=True."""
        async def mock_predict(prompt):
            return "Bullish structure confirmed by delta pressure."

        service = LLMRationaleService(llm_predict_fn=mock_predict)
        result = await service.generate_rationale({
            "market_state": "IMBALANCED",
            "poc": 100.0, "vah": 105.0, "val": 95.0,
            "direction": "LONG",
            "entry_price": 101.0, "stop_loss": 99.0, "take_profit": 108.0,
            "r_r_ratio": 3.5,
        })
        assert result.success is True
        assert result.latency_ms > 0
        assert "Bullish structure" in result.text

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        """When LLM takes >5s, returns timeout failure."""
        async def slow_predict(prompt):
            await asyncio.sleep(10)
            return "too slow"

        service = LLMRationaleService(llm_predict_fn=slow_predict)
        result = await service.generate_rationale({})
        assert result.success is False
        assert "timeout" in result.text.lower()
        assert result.latency_ms == 5000.0

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self):
        """When LLM raises, returns error message with success=False."""
        async def error_predict(prompt):
            raise RuntimeError("LLM crashed")

        service = LLMRationaleService(llm_predict_fn=error_predict)
        result = await service.generate_rationale({})
        assert result.success is False
        assert "RuntimeError" in result.text

    @pytest.mark.asyncio
    async def test_measures_latency(self):
        """Latency is measured in milliseconds."""
        async def quick_predict(prompt):
            return "quick"

        service = LLMRationaleService(llm_predict_fn=quick_predict)
        result = await service.generate_rationale({})
        assert result.latency_ms >= 0


class TestGenerateNarrative:
    """Tests for generate_narrative()."""

    @pytest.mark.asyncio
    async def test_narrative_with_state_change(self):
        """Generates narrative from state change dict."""
        captured_prompts = []

        async def mock_predict(prompt):
            captured_prompts.append(prompt)
            return "Narrative approved"

        service = LLMRationaleService(llm_predict_fn=mock_predict)
        result = await service.generate_narrative({
            "previous": "BALANCED",
            "current": "IMBALANCED",
            "trigger": "VA_BREAKOUT",
            "poc": 100.0, "vah": 105.0, "val": 95.0,
        })
        assert result.success is True
        assert result.text == "Narrative approved"
        # The prompt passed to LLM contains the transition text via _custom_prompt merge
        assert len(captured_prompts) == 1
        # _build_prompt is called which uses context fields
        assert "POC: 100.00" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_narrative_no_predict_returns_prompt(self):
        """When no predict_fn, returns the prompt as text."""
        service = LLMRationaleService(llm_predict_fn=None)
        result = await service.generate_narrative({
            "previous": "INIT",
            "current": "BALANCED",
            "trigger": "SESSION_START",
            "poc": 100.0, "vah": 105.0, "val": 95.0,
        })
        assert result.success is True
        assert "INIT" in result.text
        assert "BALANCED" in result.text

    @pytest.mark.asyncio
    async def test_narrative_handles_missing_fields(self):
        """Handles missing fields with defaults."""
        service = LLMRationaleService(llm_predict_fn=None)
        result = await service.generate_narrative({})
        assert "INIT" in result.text or "UNKNOWN" in result.text
        assert "0.00" in result.text


class TestBuildPrompt:
    """Tests for _build_prompt()."""

    def test_prompt_contains_all_fields(self):
        """Prompt contains market state, levels, direction, entry/SL/TP, R:R."""
        context = {
            "market_state": "IMBALANCED",
            "poc": 100.0, "vah": 105.0, "val": 95.0,
            "direction": "LONG",
            "entry_price": 101.0, "stop_loss": 99.0, "take_profit": 108.0,
            "r_r_ratio": 3.5,
        }
        prompt = LLMRationaleService._build_prompt(context)
        assert "IMBALANCED" in prompt
        assert "POC: 100.00" in prompt
        assert "LONG" in prompt
        assert "Entry: 101.00" in prompt
        assert "SL: 99.00" in prompt
        assert "TP: 108.00" in prompt
        assert "R:R 3.50" in prompt
        assert "Return 2-3 sentence rationale" in prompt

    def test_prompt_handles_missing_fields(self):
        """Prompt uses defaults for missing fields."""
        context = {}
        prompt = LLMRationaleService._build_prompt(context)
        assert "UNKNOWN" in prompt
        assert "0.00" in prompt
        assert "FLAT" in prompt
