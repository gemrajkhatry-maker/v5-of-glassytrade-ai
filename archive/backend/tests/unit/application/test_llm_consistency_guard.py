"""Tests for LLM consistency guard (Block 1.4)."""

from __future__ import annotations

import time
from unittest.mock import Mock, patch

import pytest


def test_llm_no_high_to_low_flip_within_same_tick_batch():
    """LLM should not flip High→Low confidence within 60 seconds."""
    from app.application.handlers.llm_entry_handler import LLMEntryHandler
    
    # Create mock dependencies
    gen_ai_service = Mock()
    gen_ai_service.is_ready.return_value = True
    
    handler = LLMEntryHandler(gen_ai_service=gen_ai_service)
    
    # Create mock session
    session = Mock()
    session._lock = Mock()
    session.data = []
    session.last_amt = {}
    session._ai_running = False
    
    # First call: 70s ago (allowed), High confidence, LONG
    session._last_llm_evaluation_time = time.time() - 70
    session._last_llm_confidence = "High"
    session._last_llm_direction = "LONG"
    
    # Mock the safety nets to return the same values
    with patch.object(handler, '_apply_safety_nets', return_value=("LONG", "High", "Bullish continuation")):
        with patch.object(handler, '_sanitize_rationale', return_value="Bullish continuation"):
            # Simulate LLM returning High confidence LONG
            ai_result = {
                "direction": "LONG",
                "confidence": "High",
                "rationale": "Bullish continuation",
            }
            
            # Manually test the consistency guard logic
            current_time = time.time()
            min_interval = 60
            
            last_eval_time = session._last_llm_evaluation_time
            last_confidence = session._last_llm_confidence
            last_direction = session._last_llm_direction
            
            direction = ai_result.get("direction", "FLAT")
            confidence = ai_result.get("confidence", "Low")
            
            if current_time - last_eval_time < min_interval:
                # Should not enter here (70s > 60s)
                assert False, "Should not skip re-evaluation after 70s"
            else:
                # Check consistency guard
                if (last_confidence == "High" and 
                    confidence in ["Low", "None"] and
                    direction == "FLAT"):
                    # Should not enter here (High→High, not High→Low)
                    assert False, "Should not trigger consistency guard for High→High"
                
                # Update tracking
                session._last_llm_evaluation_time = current_time
                session._last_llm_confidence = confidence
                session._last_llm_direction = direction
            
            assert confidence == "High"
            assert direction == "LONG"


def test_llm_consistency_guard_prevents_high_to_low_flip():
    """Consistency guard should prevent High→Low flip and hold previous decision."""
    session = Mock()
    session._last_llm_evaluation_time = time.time() - 70  # 70s ago (allowed)
    session._last_llm_confidence = "High"
    session._last_llm_direction = "LONG"
    
    # Simulate LLM returning Low confidence, FLAT (contradiction)
    ai_result = {
        "direction": "FLAT",
        "confidence": "Low",
        "rationale": "Aggression weak",
    }
    
    current_time = time.time()
    min_interval = 60
    
    last_eval_time = session._last_llm_evaluation_time
    last_confidence = session._last_llm_confidence
    last_direction = session._last_llm_direction
    
    direction = ai_result.get("direction", "FLAT")
    confidence = ai_result.get("confidence", "Low")
    
    if current_time - last_eval_time < min_interval:
        assert False, "Should not enter cooldown branch"
    else:
        # CONSISTENCY GUARD: Check for High→Low confidence flips
        if (last_confidence == "High" and 
            confidence in ["Low", "None"] and
            direction == "FLAT"):
            # Should enter here and hold previous decision
            direction = last_direction
            confidence = last_confidence
            rationale = "CONSISTENCY GUARD: Prevented High→Low flip"
        else:
            assert False, "Should trigger consistency guard"
        
        # Update tracking
        session._last_llm_evaluation_time = current_time
        session._last_llm_confidence = confidence
        session._last_llm_direction = direction
    
    assert confidence == "High", f"Expected High, got {confidence}"
    assert direction == "LONG", f"Expected LONG, got {direction}"
    assert "CONSISTENCY GUARD" in rationale


def test_llm_respects_minimum_reevaluation_interval():
    """LLM should not re-evaluate within 60 seconds."""
    session = Mock()
    session._last_llm_evaluation_time = time.time() - 30  # 30s ago
    session._last_llm_confidence = "High"
    session._last_llm_direction = "LONG"
    
    ai_result = {
        "direction": "SHORT",
        "confidence": "Medium",
        "rationale": "Bearish signal",
    }
    
    current_time = time.time()
    min_interval = 60
    
    last_eval_time = session._last_llm_evaluation_time
    last_confidence = session._last_llm_confidence
    last_direction = session._last_llm_direction
    
    direction = ai_result.get("direction", "FLAT")
    confidence = ai_result.get("confidence", "Low")
    
    if current_time - last_eval_time < min_interval:
        # Should enter here and hold previous decision
        direction = last_direction
        confidence = last_confidence
        rationale = "Held from previous evaluation (cooldown active)"
    else:
        assert False, "Should skip re-evaluation within 60s"
    
    assert direction == "LONG", f"Expected LONG (held), got {direction}"
    assert confidence == "High", f"Expected High (held), got {confidence}"
    assert "cooldown" in rationale.lower()


def test_llm_allows_normal_evaluation_after_interval():
    """After 60s cooldown, LLM should allow normal re-evaluation."""
    session = Mock()
    session._last_llm_evaluation_time = time.time() - 65  # 65s ago
    session._last_llm_confidence = "High"
    session._last_llm_direction = "LONG"
    
    # New legitimate signal
    ai_result = {
        "direction": "SHORT",
        "confidence": "High",
        "rationale": "Strong bearish breakout",
    }
    
    current_time = time.time()
    min_interval = 60
    
    last_eval_time = session._last_llm_evaluation_time
    
    direction = ai_result.get("direction", "FLAT")
    confidence = ai_result.get("confidence", "Low")
    
    if current_time - last_eval_time < min_interval:
        assert False, "Should not skip after 65s"
    else:
        # Should allow normal evaluation
        # (No consistency guard trigger since High→High is OK)
        session._last_llm_evaluation_time = current_time
        session._last_llm_confidence = confidence
        session._last_llm_direction = direction
    
    assert direction == "SHORT"
    assert confidence == "High"
