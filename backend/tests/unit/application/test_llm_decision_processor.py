"""Tests for LLM decision processor module."""

import pytest
from app.application.handlers.llm_decision_processor import (
    LLMDecisionProcessor,
    update_llm_memory,
)


class TestLLMDecisionProcessor:
    """Tests for decision processing logic."""

    def test_init(self):
        """Test initialization."""
        proc = LLMDecisionProcessor(allow_short=False)
        assert proc._allow_short is False

    def test_apply_safety_nets_buy_only(self):
        """Test buy-only mode blocks short."""
        proc = LLMDecisionProcessor(allow_short=False)
        dir, conf, rat = proc.apply_safety_nets("SHORT", 0.7, "test", None, None)
        assert dir == "FLAT"
        assert "BUY-ONLY" in rat

    def test_apply_safety_nets_short_allowed(self):
        """Test short allowed when configured."""
        proc = LLMDecisionProcessor(allow_short=True)
        dir, conf, rat = proc.apply_safety_nets("SHORT", 0.7, "test", None, None)
        assert dir == "SHORT"
        assert rat == "test"

    def test_apply_safety_nets_vwap_extreme(self):
        """Test VWAP extreme check."""
        proc = LLMDecisionProcessor(allow_short=True)
        amt = type('X', (), {
            'vwap_upper_2': 100.0,
            'aggression': 1.5
        })()
        tick = type('X', (), {'close': 101.5})()
        
        dir, conf, rat = proc.apply_safety_nets("LONG", 0.7, "test", tick, amt)
        assert "VWAP extreme" in rat

    def test_mark_ai_done(self):
        """Test AI done flag reset."""
        proc = LLMDecisionProcessor()
        session = type('X', (), {'_lock': None, '_ai_running': True, '_llm_status': 'BUSY'})()
        proc.mark_ai_done(session)


class TestUpdateLLMMemory:
    """Tests for memory update."""

    def test_update_memory(self):
        """Test memory buffer update."""
        session = type('X', (), {'_llm_memory': []})()
        update_llm_memory(session, "LONG", "Test rationale for signal")
        assert len(session._llm_memory) == 1
        assert "LONG" in session._llm_memory[0]

    def test_memory_cap(self):
        """Test memory buffer cap."""
        session = type('X', (), {'_llm_memory': list(range(10))})()
        update_llm_memory(session, "LONG", "New")
        assert len(session._llm_memory) == 5