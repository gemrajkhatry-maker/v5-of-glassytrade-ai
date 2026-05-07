"""Tests for llm_contract.py — LLM response schema and constants."""
from __future__ import annotations

import pytest

from app.domain.fabio_ai.services import llm_contract


class TestEntryResponseSchemaInstruction:
    """Tests for entry_response_schema_instruction()."""

    def teardown_method(self):
        """Clear LRU cache between tests."""
        llm_contract.entry_response_schema_instruction.cache_clear()

    def test_without_short_restriction(self):
        """allow_short=False restricts to LONG or FLAT."""
        result = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert '"LONG" | "FLAT"' in result
        assert '"SHORT"' not in result

    def test_with_short_allowed(self):
        """allow_short=True includes SHORT option."""
        result = llm_contract.entry_response_schema_instruction(allow_short=True)
        assert '"LONG" | "SHORT" | "FLAT"' in result

    def test_includes_confidence_options(self):
        """Schema includes High/Medium/Low confidence options."""
        result = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert '"High"' in result
        assert '"Medium"' in result
        assert '"Low"' in result

    def test_includes_market_state_field(self):
        """Schema includes market_state field with valid options."""
        result = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert '"market_state"' in result
        assert "BALANCED" in result
        assert "IMBALANCED" in result
        assert "PROBING" in result

    def test_includes_rationale_field(self):
        """Schema includes rationale field description."""
        result = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert '"rationale"' in result
        assert "market state" in result.lower()

    def test_demands_valid_json(self):
        """Schema demands valid JSON only."""
        result = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert "VALID JSON" in result
        assert "no markdown" in result.lower()
        assert "no extra text" in result.lower()

    def test_lru_cache_returns_same_object(self):
        """Repeated calls return identical cached result."""
        r1 = llm_contract.entry_response_schema_instruction(allow_short=False)
        r2 = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert r1 is r2

    def test_cache_clear_allows_regeneration(self):
        """After cache_clear(), new call returns equal but different object."""
        r1 = llm_contract.entry_response_schema_instruction(allow_short=False)
        llm_contract.entry_response_schema_instruction.cache_clear()
        r2 = llm_contract.entry_response_schema_instruction(allow_short=False)
        assert r1 == r2
        assert r1 is not r2


class TestContractConstants:
    """Tests for module-level constants."""

    def test_entry_contract_version(self):
        """Contract version is defined."""
        assert llm_contract.ENTRY_CONTRACT_VERSION == "entry-json-v1"

    def test_canonical_model_family(self):
        """Canonical model family is defined."""
        assert llm_contract.CANONICAL_RUNTIME_MODEL_FAMILY == "gemma-mlx"

    def test_entry_response_keys(self):
        """Required response keys are defined."""
        assert llm_contract.ENTRY_RESPONSE_KEYS == (
            "direction",
            "rationale",
            "confidence",
            "market_state",
        )

    def test_entry_json_runtime_reminder(self):
        """Runtime reminder enforces JSON-only output."""
        reminder = llm_contract.ENTRY_JSON_RUNTIME_REMINDER
        assert "JSON" in reminder
        assert "direction" not in reminder.lower() or "rationale" in reminder.lower()
