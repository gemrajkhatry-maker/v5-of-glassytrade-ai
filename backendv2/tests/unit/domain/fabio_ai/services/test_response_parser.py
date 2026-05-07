"""Tests for LLM response parsing."""
import pytest
from app.domain.fabio_ai.services.response_parser import (
    parse_entry_response, parse_overseer_response, OverseerAction
)


class TestParseEntryResponse:
    """Tests for parse_entry_response()."""

    def test_clean_json(self):
        """Valid JSON parses directly."""
        text = '{"direction": "LONG", "confidence": "High", "rationale": "test"}'
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "High"

    def test_embedded_json(self):
        """JSON embedded in text gets extracted and normalized."""
        text = 'Market looks bullish. {"direction": "SHORT", "confidence": "Medium", "rationale": "reason"}'
        result = parse_entry_response(text)
        assert result["direction"] == "SHORT"

    def test_invalid_json_keyword_fallback(self):
        """Invalid JSON falls back to keyword parsing."""
        text = "I think we should go LONG on this market with 75% confidence"
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "75%"

    def test_keyword_buy_maps_to_long(self):
        """BUY keyword maps to LONG direction."""
        text = "Buy signal detected"
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"

    def test_keyword_sell_maps_to_short(self):
        """SELL keyword maps to SHORT direction."""
        text = "Sell signal detected"
        result = parse_entry_response(text)
        assert result["direction"] == "SHORT"

    def test_no_keyword_maps_to_flat(self):
        """No direction keyword maps to FLAT."""
        text = "Market is neutral"
        result = parse_entry_response(text)
        assert result["direction"] == "FLAT"

    def test_confidence_from_percentage(self):
        """Confidence extracted from percentage in text."""
        text = "LONG with 80% confidence"
        result = parse_entry_response(text)
        assert result["confidence"] == "80%"

    def test_clean_json_passes_through(self):
        """Clean JSON passes through as-is."""
        text = '{"direction": "LONG", "confidence": "high"}'
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "high"

    def test_structured_key_value_parse(self):
        """Key-value format parses correctly."""
        text = "Direction: LONG\nConfidence: 85%\nRationale: strong trend"
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"

    def test_numeric_confidence_in_embedded_json(self):
        """Embedded JSON with numeric confidence gets normalized."""
        text = 'Analysis: {"direction": "LONG", "confidence": "1"}'
        result = parse_entry_response(text)
        assert result["confidence"] == "High"

    def test_direction_normalized_in_embedded(self):
        """Invalid direction in embedded JSON normalized to FLAT."""
        text = 'Analysis: {"direction": "INVALID", "confidence": "High"}'
        result = parse_entry_response(text)
        assert result["direction"] == "FLAT"

    def test_rationale_truncated_in_embedded(self):
        """Long rationale in embedded JSON gets truncated."""
        long_text = "x" * 200
        text = f'Analysis: {{"direction": "LONG", "rationale": "{long_text}"}}'
        result = parse_entry_response(text)
        assert len(result["rationale"]) <= 140


class TestParseOverseerResponse:
    """Tests for parse_overseer_response()."""

    def test_clean_json_exit(self):
        """Valid JSON with EXIT action."""
        text = '{"action": "EXIT", "urgency": "HIGH", "confidence": 0.9, "rationale": "stop hit"}'
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "EXIT"
        assert result.urgency == "HIGH"
        assert result.confidence == 0.9

    def test_clean_json_hold(self):
        """Valid JSON with HOLD action."""
        text = '{"action": "HOLD", "urgency": "NORMAL", "confidence": 0.5}'
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "HOLD"

    def test_keyword_exit(self):
        """EXIT keyword detected in text."""
        text = "We should EXIT this position immediately"
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "EXIT"

    def test_keyword_add(self):
        """ADD/SCALE keyword detected."""
        text = "Consider adding to this position"
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "ADD"

    def test_keyword_move_sl(self):
        """MOVE/ADJUST keyword detected."""
        text = "Move the stop loss to breakeven"
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "MOVE_SL"

    def test_keyword_hold_default(self):
        """No action keyword defaults to HOLD."""
        text = "Keep position as is"
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "HOLD"

    def test_urgent_flag(self):
        """URGENT keyword sets high urgency."""
        text = "URGENT: exit now!"
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.urgency == "HIGH"

    def test_confidence_from_number(self):
        """Confidence extracted from number in text."""
        text = "EXIT with 85 confidence"
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.confidence == 0.85

    def test_embedded_json_overseer(self):
        """Embedded JSON in overseer text."""
        text = 'Analysis: {"action": "EXIT", "urgency": "HIGH", "confidence": 0.8}'
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.action == "EXIT"

    def test_default_values(self):
        """Missing fields use defaults."""
        text = '{"action": "HOLD"}'
        pos_state = {}
        result = parse_overseer_response(text, pos_state)
        assert result.urgency == "NORMAL"
        assert result.confidence == 0.0
        assert result.rationale == ""
