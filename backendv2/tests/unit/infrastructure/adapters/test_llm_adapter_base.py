"""Tests for LLM adapter base class.

Characterization and contract tests for shared LLM inference utilities.
"""
from __future__ import annotations

import json

import pytest

from app.infrastructure.adapters.llm_adapter_base import (
    BaseLLMInferenceAdapter,
    ENTRY_JSON_RUNTIME_REMINDER,
)


class TestEntryJsonRuntimeReminder:
    """Test the shared reminder constant."""

    def test_contains_json_keyword(self):
        assert "JSON" in ENTRY_JSON_RUNTIME_REMINDER

    def test_not_empty(self):
        assert len(ENTRY_JSON_RUNTIME_REMINDER) > 0


class TestExtractJsonCandidate:
    """Test JSON extraction from LLM responses."""

    def test_extracts_clean_json(self):
        text = '{"direction": "LONG", "confidence": 0.85}'
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result == {"direction": "LONG", "confidence": 0.85}

    def test_extracts_json_with_markdown(self):
        text = 'Some text\n```json\n{"direction": "SHORT"}\n```\nMore text'
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result == {"direction": "SHORT"}

    def test_extracts_json_with_extra_text(self):
        text = 'Here is my analysis:\n{"direction": "LONG", "confidence": 0.9}\nHope this helps!'
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result == {"direction": "LONG", "confidence": 0.9}

    def test_returns_none_for_no_json(self):
        text = "This is just plain text with no JSON object"
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        text = '{"direction": "LONG", "confidence": }'  # Invalid
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result is None

    def test_extracts_nested_json(self):
        text = '{"level1": {"level2": "value"}}'
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result == {"level1": {"level2": "value"}}

    def test_fails_on_multiple_json_objects(self):
        """Current implementation cannot handle multiple top-level JSON objects."""
        text = '{"first": 1} some text {"second": 2}'
        result = BaseLLMInferenceAdapter._extract_json_candidate(text)
        assert result is None  # Known limitation


class TestWaitUntilReady:
    """Test the wait_until_ready polling loop."""

    def test_returns_true_when_ready_immediately(self):
        class ReadyAdapter(BaseLLMInferenceAdapter):
            def __init__(self):
                self._ready = True
            def is_ready(self):
                return self._ready
            def predict(self, prompt, **kwargs):
                return ""

        adapter = ReadyAdapter()
        assert adapter.wait_until_ready(timeout=1.0) is True

    def test_returns_false_when_never_ready(self):
        class NeverReadyAdapter(BaseLLMInferenceAdapter):
            def __init__(self):
                self._ready = False
            def is_ready(self):
                return self._ready
            def predict(self, prompt, **kwargs):
                return ""

        adapter = NeverReadyAdapter()
        assert adapter.wait_until_ready(timeout=0.1) is False

    def test_polls_until_ready(self):
        class DelayedReadyAdapter(BaseLLMInferenceAdapter):
            def __init__(self):
                self._calls = 0
            def is_ready(self):
                self._calls += 1
                return self._calls >= 3
            def predict(self, prompt, **kwargs):
                return ""

        adapter = DelayedReadyAdapter()
        assert adapter.wait_until_ready(timeout=1.0, poll_interval=0.01) is True
        assert adapter._calls >= 3


class TestSingletonMixin:
    """Test singleton behavior."""

    def test_same_instance_returned(self):
        class TestAdapter(BaseLLMInferenceAdapter):
            _instance = None
            _init_lock = None
            def __init__(self):
                pass
            def is_ready(self):
                return True
            def predict(self, prompt, **kwargs):
                return ""

        # Reset for test
        TestAdapter._instance = None
        TestAdapter._init_lock = None

        a1 = TestAdapter()
        a2 = TestAdapter()
        assert a1 is a2
