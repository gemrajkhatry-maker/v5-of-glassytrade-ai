"""Tests for LLM response parsing – characterization.

Validates the extraction of direction, confidence, and rationale from various
LLM response formats before we refactor into a dedicated parser service.
"""
from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.llm_response_parser import LLMResponseParser


class TestLLMResponseParser:
    """Characterization tests for LLMResponseParser."""

    def test_parse_json_line_with_direction_confidence(self):
        text = '{"direction": "LONG", "confidence": "HIGH", "rationale": "Strong absorption"}'
        result = LLMResponseParser.parse(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "HIGH"
        assert result["rationale"] == "Strong absorption"

    def test_parse_json_with_trailing_newline(self):
        text = '{"direction":"SHORT","confidence":"LOW"}\n'
        result = LLMResponseParser.parse(text)
        assert result["direction"] == "SHORT"
        assert result["confidence"] == "LOW"

    def test_parse_json_markdown_fenced(self):
        text = '```json\n{"direction": "LONG", "confidence": "MEDIUM"}\n```'
        result = LLMResponseParser.parse(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "MEDIUM"

    def test_parse_json_with_extra_text_before(self):
        text = 'Here is my analysis:\n{"direction":"LONG"}\nEnd'
        result = LLMResponseParser.parse(text)
        assert result["direction"] == "LONG"

    def test_parse_returns_none_on_invalid_json(self):
        text = 'This is plain text with no JSON'
        result = LLMResponseParser.parse(text)
        assert result is None

    def test_sanitize_removes_llm_notes(self):
        raw = "LONG - I see absorption\n(Note: LLM generated)"
        clean = LLMResponseParser.sanitize(raw, "LONG")
        assert "(Note:" not in clean

    def test_sanitize_ensures_line_at_end(self):
        raw = "LONG - pattern"
        clean = LLMResponseParser.sanitize(raw, "LONG")
        assert clean.endswith(".")

    def test_sanitize_drops_when_direction_mismatch(self):
        raw = "SHORT something"
        clean = LLMResponseParser.sanitize(raw, "LONG")
        # Mismatch leads to trimming to single word "?" or empty
        assert "SHORT" not in clean

    def test_parse_line_based_response(self):
        text = "direction=LONG\nconfidence=HIGH\nrationale=Clear breakout"
        result = LLMResponseParser.parse_line_based(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "HIGH"
        assert result["rationale"] == "Clear breakout"

    def test_parse_line_based_ignores_other_keys(self):
        text = "direction=SHORT\nsome_other=value\nconfidence=LOW"
        result = LLMResponseParser.parse_line_based(text)
        assert result["direction"] == "SHORT"
        assert result["confidence"] == "LOW"
        assert "some_other" not in result

    def test_parse_line_based_returns_none_if_missing_direction(self):
        text = "confidence=HIGH\nrationale=test"
        result = LLMResponseParser.parse_line_based(text)
        assert result is None