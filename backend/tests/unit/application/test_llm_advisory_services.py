"""Tests for PreCandleAdvisor and PostTradeAnalyst services."""

import pytest

from app.application.handlers.pre_candle_advisor import AdvisoryResult, PreCandleAdvisor
from app.application.handlers.post_trade_analyst import (
    PostTradeAnalysis,
    PostTradeAnalyst,
    build_post_trade_prompt,
    parse_post_trade_response,
)
from app.domain.fabio_ai.services.prompt_builder import (
    build_advisory_prompt,
    parse_advisory_response,
)


# ---- PreCandleAdvisor Tests ----


class TestAdvisoryResult:
    def test_immutable(self):
        result = AdvisoryResult(
            symbol="NIFTY", scenario="test", expected_setup="test", key_levels="test"
        )
        assert result.symbol == "NIFTY"
        assert result.timed_out is False

    def test_timed_out_flag(self):
        result = AdvisoryResult(
            symbol="NIFTY",
            scenario="",
            expected_setup="",
            key_levels="",
            timed_out=True,
        )
        assert result.timed_out is True


class TestBuildAdvisoryPrompt:
    def test_prompt_contains_symbol(self):
        from app.domain.trading.models.value_objects import OHLC, AMTResult

        tick = OHLC.create(
            time="2024-01-01T09:15:00",
            open=24000,
            high=24100,
            low=23950,
            close=24050,
            volume=1000,
        )
        amt = AMTResult(
            market_state="BALANCED",
            poc=24025,
            value_area_high=24100,
            value_area_low=23950,
        )
        prompt = build_advisory_prompt(symbol="NIFTY", tick=tick, amt_result=amt)
        assert "NIFTY" in prompt
        assert "BALANCED" in prompt


class TestParseAdvisoryResponse:
    def test_json_response(self):
        raw = '{"scenario": "balanced", "expected_setup": "mean reversion", "key_levels": "24000"}'
        parsed = parse_advisory_response(raw)
        assert parsed["scenario"] == "balanced"
        assert parsed["expected_setup"] == "mean reversion"

    def test_non_json_fallback(self):
        parsed = parse_advisory_response("Market is balanced near POC")
        assert "scenario" in parsed
        assert len(parsed["scenario"]) > 0


class TestPreCandleAdvisorShouldFire:
    def test_disabled_returns_false(self):
        from unittest.mock import MagicMock

        advisor = PreCandleAdvisor(MagicMock(), enabled=False)
        assert advisor.should_fire("NIFTY", 4) is False

    def test_wrong_bar_minute(self):
        from unittest.mock import MagicMock

        svc = MagicMock()
        svc.is_ready.return_value = True
        advisor = PreCandleAdvisor(svc, enabled=True)
        assert advisor.should_fire("NIFTY", 2) is False

    def test_correct_bar_minute(self):
        from unittest.mock import MagicMock

        svc = MagicMock()
        svc.is_ready.return_value = True
        advisor = PreCandleAdvisor(svc, enabled=True)
        assert advisor.should_fire("NIFTY", 4) is True


# ---- PostTradeAnalyst Tests ----


class TestBuildPostTradePrompt:
    def test_prompt_contains_trade_details(self):
        prompt = build_post_trade_prompt(
            symbol="NIFTY",
            entry_price=24000.0,
            exit_price=24100.0,
            side="LONG",
            pnl=2500.0,
            hold_time_seconds=300.0,
            close_reason="TAKE_PROFIT",
        )
        assert "NIFTY" in prompt
        assert "24000" in prompt
        assert "TAKE_PROFIT" in prompt


class TestParsePostTradeResponse:
    def test_json_response(self):
        raw = '{"quality_score": 8, "mistake": "none", "improvement": "good entry"}'
        parsed = parse_post_trade_response(raw)
        assert parsed["quality_score"] == 8
        assert parsed["mistake"] == "none"

    def test_quality_score_clamped(self):
        raw = '{"quality_score": 15, "mistake": "none", "improvement": "test"}'
        parsed = parse_post_trade_response(raw)
        assert parsed["quality_score"] == 10

    def test_non_json_fallback(self):
        parsed = parse_post_trade_response("Good trade, well managed")
        assert "quality_score" in parsed
        assert parsed["quality_score"] == 5  # default


class TestPostTradeAnalysis:
    def test_immutable(self):
        result = PostTradeAnalysis(
            symbol="NIFTY", quality_score=7, mistake="none", improvement="test"
        )
        assert result.quality_score == 7
