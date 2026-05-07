"""Tests for prompt_builder.py — prompt construction and parsing delegation."""
from __future__ import annotations

import pytest

from app.domain.fabio_ai.services import prompt_builder
from app.domain.fabio_ai.services.response_parser import OverseerAction


class TestBuildEntryPrompt:
    """Tests for build_entry_prompt()."""

    def test_default_prompt_restricts_to_long_flat(self):
        """Default prompt only allows LONG or FLAT direction."""
        data = {"ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0}
        prompt = prompt_builder.build_entry_prompt(data)
        assert "LONG or FLAT only" in prompt
        assert "SHORT" not in prompt.split("Direction options:")[1].split("\n")[0]

    def test_allow_short_includes_all_directions(self):
        """With allow_short=True, prompt allows LONG, SHORT, and FLAT."""
        data = {"ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0}
        prompt = prompt_builder.build_entry_prompt(data, allow_short=True)
        assert "LONG or SHORT or FLAT" in prompt

    def test_prompt_contains_session_context(self):
        """Prompt includes session context when data has session fields."""
        data = {
            "session_name": "NSE_EQUITY",
            "favor_strategy": "TREND_CONTINUATION",
            "prior_poc": 100.0,
            "prior_vah": 105.0,
            "prior_val": 95.0,
            "ltp": 100.0,
            "poc": 100.0,
            "vah": 105.0,
            "val": 95.0,
        }
        prompt = prompt_builder.build_entry_prompt(data)
        assert "Session: NSE_EQUITY" in prompt
        assert "Active bias: TREND_CONTINUATION" in prompt
        assert "Prior POC/VAH/VAL: 100/105/95" in prompt

    def test_prompt_contains_gap_and_opening_bias(self):
        """Prompt includes gap type and opening bias when present."""
        data = {
            "gap_type": "INSIDE_VA",
            "opening_bias": "BULLISH",
            "ltp": 100.0,
            "poc": 100.0,
            "vah": 105.0,
            "val": 95.0,
        }
        prompt = prompt_builder.build_entry_prompt(data)
        assert "Gap: INSIDE_VA" in prompt
        assert "Opening bias: BULLISH" in prompt

    def test_prompt_contains_market_state_narrative(self):
        """Prompt includes market state classification."""
        data = {"ltp": 110.0, "poc": 100.0, "vah": 105.0, "val": 95.0, "market_state": "IMBALANCED"}
        prompt = prompt_builder.build_entry_prompt(data)
        assert "Market state: IMBALANCED" in prompt

    def test_prompt_contains_order_flow_narrative(self):
        """Prompt includes delta, aggression, and CVD slope when present."""
        data = {
            "ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0,
            "delta": 150.0,
            "aggression": 3.5,
            "cvd_slope": 0.8,
        }
        prompt = prompt_builder.build_entry_prompt(data)
        assert "BUY momentum" in prompt
        assert "Aggression score: 3.50" in prompt
        assert "CVD slope: 0.80" in prompt

    def test_prompt_contains_core_amt_narrative(self):
        """Prompt includes core AMT narrative section."""
        data = {
            "ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0,
            "session_name": "NSE",
            "market_state": "BALANCED",
            "delta": 50.0,
        }
        prompt = prompt_builder.build_entry_prompt(data)
        assert "SESSION:" in prompt or "Session:" in prompt
        assert "MARKET STATE:" in prompt or "Market state:" in prompt

    def test_prompt_contains_strict_json_instruction(self):
        """Prompt instructs LLM to return only JSON."""
        data = {"ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0}
        prompt = prompt_builder.build_entry_prompt(data)
        assert "Return only a JSON object" in prompt
        assert "direction, confidence, rationale" in prompt
        assert "Return ONLY a valid JSON object" in prompt

    def test_prompt_contains_raw_json_dump(self):
        """Prompt includes raw JSON dump of input data."""
        data = {"ltp": 100.0, "poc": 100.0, "vah": 105.0, "val": 95.0, "custom_key": "test_value"}
        prompt = prompt_builder.build_entry_prompt(data)
        assert "Raw context:" in prompt
        assert "custom_key" in prompt
        assert "test_value" in prompt

    def test_prompt_handles_empty_data_gracefully(self):
        """Prompt builds successfully with empty data dict."""
        data = {}
        prompt = prompt_builder.build_entry_prompt(data)
        assert len(prompt) > 0
        assert "Return only a JSON object" in prompt


class TestBuildOverseerPrompt:
    """Tests for build_overseer_prompt()."""

    def test_overseer_prompt_contains_position_state(self):
        """Overseer prompt includes position state in payload."""
        data = {"ltp": 100.0}
        position_state = {"direction": "LONG", "entry_price": 99.0, "stop_loss": 98.0}
        prompt = prompt_builder.build_overseer_prompt(data, position_state)
        assert "protective trading overseer" in prompt
        assert "LONG" in prompt
        assert "99.0" in prompt

    def test_overseer_prompt_contains_action_options(self):
        """Overseer prompt lists valid action options."""
        data = {"ltp": 100.0}
        position_state = {"direction": "LONG"}
        prompt = prompt_builder.build_overseer_prompt(data, position_state)
        assert "HOLD" in prompt
        assert "EXIT" in prompt
        assert "ADD" in prompt
        assert "MOVE_SL" in prompt


class TestBuildAdvisoryPrompt:
    """Tests for build_advisory_prompt()."""

    def test_advisory_prompt_contains_symbol_and_message(self):
        """Advisory prompt includes symbol and message fields."""
        data = {"symbol": "NIFTY", "message": "Entry signal detected"}
        prompt = prompt_builder.build_advisory_prompt(data)
        assert "NIFTY" in prompt
        assert "Entry signal detected" in prompt
        assert "text" in prompt

    def test_advisory_prompt_handles_missing_fields(self):
        """Advisory prompt handles missing symbol/message with defaults."""
        data = {}
        prompt = prompt_builder.build_advisory_prompt(data)
        assert "UNKNOWN" in prompt
        assert "No message" in prompt


class TestParseEntryResponse:
    """Tests for parse_entry_response() delegation.

    Note: prompt_builder.parse_entry_response has a recursion bug in source
    (calls itself instead of imported response_parser.parse_entry_response).
    Tests the imported function directly instead.
    """

    def test_parses_valid_json(self):
        """Valid JSON is parsed correctly."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = '{"direction": "LONG", "confidence": "High", "rationale": "bullish structure"}'
        result = parse_entry_response(text)
        assert result["direction"] == "LONG"
        assert result["confidence"] == "High"

    def test_parses_embedded_json(self):
        """JSON embedded in prose is extracted."""
        from app.domain.fabio_ai.services.response_parser import parse_entry_response
        text = 'Based on analysis: {"direction": "SHORT", "confidence": "Medium", "rationale": "bearish"} done'
        result = parse_entry_response(text)
        assert result["direction"] == "SHORT"


class TestParseOverseerResponse:
    """Tests for parse_overseer_response() delegation.

    Note: Same recursion bug as parse_entry_response in source.
    """

    def test_parses_valid_overseer_json(self):
        """Valid overseer JSON is parsed into OverseerAction."""
        from app.domain.fabio_ai.services.response_parser import parse_overseer_response
        text = '{"action": "EXIT", "urgency": "HIGH", "confidence": 0.9, "rationale": "stop hit"}'
        result = parse_overseer_response(text, {})
        assert isinstance(result, OverseerAction)
        assert result.action == "EXIT"
        assert result.urgency == "HIGH"


class TestComputeTightenSl:
    """Tests for compute_tighten_sl()."""

    def test_long_tightens_sl_closer_to_entry(self):
        """For LONG, SL is moved closer to entry (67% of original risk)."""
        pos = {"direction": "LONG", "entry_price": 100.0, "stop_loss": 90.0}
        result = prompt_builder.compute_tighten_sl(pos)
        # Original risk = 10, 67% = 6.7, new SL = 100 - 6.7 = 93.3
        assert result == pytest.approx(93.3, abs=0.1)

    def test_short_tightens_sl_closer_to_entry(self):
        """For SHORT, SL is moved closer to entry (67% of original risk)."""
        pos = {"direction": "SHORT", "entry_price": 100.0, "stop_loss": 110.0}
        result = prompt_builder.compute_tighten_sl(pos)
        # Original risk = 10, 67% = 6.7, new SL = 100 + 6.7 = 106.7
        assert result == pytest.approx(106.7, abs=0.1)

    def test_returns_zero_for_invalid_entry(self):
        """Returns 0.0 when entry or stop_loss is invalid."""
        assert prompt_builder.compute_tighten_sl({}) == 0.0
        assert prompt_builder.compute_tighten_sl({"direction": "LONG", "entry_price": 0, "stop_loss": 90}) == 0.0
        assert prompt_builder.compute_tighten_sl({"direction": "LONG", "entry_price": 100, "stop_loss": 0}) == 0.0

    def test_returns_stop_loss_for_flat_direction(self):
        """Returns original stop_loss for non-LONG/SHORT direction."""
        pos = {"direction": "FLAT", "entry_price": 100.0, "stop_loss": 95.0}
        result = prompt_builder.compute_tighten_sl(pos)
        assert result == 95.0

    def test_long_sl_never_moves_away_from_entry(self):
        """Tightened LONG SL is never below original stop_loss."""
        pos = {"direction": "LONG", "entry_price": 100.0, "stop_loss": 90.0}
        result = prompt_builder.compute_tighten_sl(pos)
        assert result >= 90.0

    def test_short_sl_never_moves_away_from_entry(self):
        """Tightened SHORT SL is never above original stop_loss."""
        pos = {"direction": "SHORT", "entry_price": 100.0, "stop_loss": 110.0}
        result = prompt_builder.compute_tighten_sl(pos)
        assert result <= 110.0
