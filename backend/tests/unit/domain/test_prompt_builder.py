"""Contract tests for prompt_builder.py — pure string functions, no mocks."""

import pytest
from app.domain.fabio_ai.services.prompt_builder import (
    build_entry_prompt,
    parse_entry_response,
    build_overseer_prompt,
    parse_overseer_response,
    compute_tighten_sl,
    OverseerAction,
)
from app.domain.trading.models.value_objects import OHLC, AMTResult, FootprintCandle, FootprintLevel
from app.domain.fabio_ai.services.session_context import SessionInfo


def _tick(close=100, delta=50, volume=500, vwap=100):
    return OHLC(time="t", open=close, high=close*1.01, low=close*0.99,
                close=close, volume=volume, vwap=vwap, delta=delta)


def _amt(poc=100, vah=105, val=95, market_state="BALANCED"):
    return AMTResult(market_state=market_state, poc=poc,
                     value_area_high=vah, value_area_low=val)


def _pos_state(**overrides):
    base = {
        "position_id": "P1", "side": "LONG", "entry_price": 100.0,
        "current_price": 105.0, "unrealized_pnl_pct": 0.05,
        "time_in_trade_secs": 30.0, "stop_loss": 95.0, "take_profit": 110.0,
        "partial_taken": False, "trailing_active": False,
    }
    base.update(overrides)
    return base


class TestBuildEntryPrompt:
    def test_returns_string(self):
        prompt = build_entry_prompt({"ltp": 100, "vah": 105, "val": 95, "poc": 100, "delta": 50})
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_includes_val_when_near(self):
        prompt = build_entry_prompt({"ltp": 95, "vah": 105, "val": 95, "poc": 100, "delta": -200})
        assert "Value Area Low" in prompt or "VAL" in prompt

    def test_includes_cvd_divergence(self):
        prompt = build_entry_prompt({"ltp": 100, "vah": 105, "val": 95, "poc": 100, "delta": 0,
                                     "cvd_divergence": "BEARISH_DIV"})
        assert "CVD" in prompt and "divergence" in prompt.lower()

    def test_includes_volume_bubbles(self):
        prompt = build_entry_prompt({"ltp": 100, "vah": 105, "val": 95, "poc": 100, "delta": 0,
                                     "volume_bubbles": "BUY bubble at 100"})
        assert "Volume bubbles" in prompt


class TestParseEntryResponse:
    def test_long(self):
        r = parse_entry_response("Trigger: **Enter Long**")
        assert r["direction"] == "LONG"

    def test_short(self):
        r = parse_entry_response("Trigger: **Enter Short**")
        assert r["direction"] == "SHORT"

    def test_flat_explicit(self):
        r = parse_entry_response("Stay Flat")
        assert r["direction"] == "FLAT"

    def test_empty_defaults_flat(self):
        r = parse_entry_response("")
        assert r["direction"] == "FLAT"

    def test_high_confidence(self):
        r = parse_entry_response("Trigger: **Enter Long** with size. Full allocation.")
        assert r["direction"] == "LONG"
        assert r["confidence"] == "High"


class TestBuildOverseerPrompt:
    def test_includes_position_info(self):
        prompt = build_overseer_prompt(_pos_state(), _tick(), _amt())
        assert "LONG" in prompt
        assert "100.00" in prompt
        assert "105.00" in prompt

    def test_includes_market_state(self):
        prompt = build_overseer_prompt(_pos_state(), _tick(), _amt(market_state="Trending"))
        assert "Trending" in prompt


class TestParseOverseerResponse:
    def test_hold(self):
        r = parse_overseer_response("Action: Hold\nReason: Conviction unchanged", _pos_state())
        assert r.action == "HOLD"
        assert "Conviction" in r.reason

    def test_tighten_sl_with_price(self):
        # The parser currently ignores 'Action:' keyword if it successfully parses JSON
        # For legacy keyword parsing, it expects 'tighten' or 'move stop'
        r = parse_overseer_response('{"action": "TIGHTEN_SL", "new_sl_price": 102.5}', _pos_state())
        assert r.action == "TIGHTEN_SL"
        assert r.new_sl_price == pytest.approx(102.5)

    def test_full_exit(self):
        r = parse_overseer_response('{"action": "FULL_EXIT"}', _pos_state())
        assert r.action == "FULL_EXIT"

    def test_partial_exit(self):
        r = parse_overseer_response('{"action": "PARTIAL_EXIT"}', _pos_state())
        assert r.action == "PARTIAL_EXIT"

    def test_keyword_fallback(self):
        r = parse_overseer_response("Close position now!", _pos_state())
        assert r.action == "FULL_EXIT"

    def test_default_hold(self):
        r = parse_overseer_response("I think the market looks fine", _pos_state())
        assert r.action == "HOLD"


class TestComputeTightenSL:
    def test_long_midpoint(self):
        sl = compute_tighten_sl({"side": "LONG", "current_price": 110, "stop_loss": 90})
        assert sl == 100.0  # midpoint

    def test_short_midpoint(self):
        sl = compute_tighten_sl({"side": "SHORT", "current_price": 90, "stop_loss": 110})
        assert sl == 100.0


class TestOverseerContextEnrichment:
    """Tests for overseer prompt enrichment with session, profile, OI, footprint data."""

    def _session_info(self, **overrides):
        # Note: SessionInfo in session_context.py has specific fields
        # Using a dummy object for testing if actual class is missing some fields
        class DummySession:
            def __init__(self, **kwargs):
                for k, v in kwargs.items(): setattr(self, k, v)
        
        defaults = dict(
            session="NSE_PRIMARY", phase=2, is_london=False, is_new_york=False,
            opening_inventory_bias="NEUTRAL", favor_strategy="TREND_CONTINUATION",
            allow_entry=True, allow_trend=True, allow_reversion=True,
            force_exit=False, market="NSE", gap_type="INSIDE", ib_high=100, ib_low=90
        )
        defaults.update(overrides)
        return DummySession(**defaults)

    def test_prompt_includes_session_phase(self):
        """Session info provided -> prompt contains session line."""
        si = self._session_info(session="NSE_PRIMARY", favor_strategy="TREND_CONTINUATION")
        prompt = build_overseer_prompt(_pos_state(), _tick(), _amt(), session_info=si)
        assert "Session: NSE_PRIMARY" in prompt
        assert "TREND_CONTINUATION" in prompt

    def test_prompt_includes_profile_shape(self):
        """AMTResult with profile_shape='b' -> prompt contains 'b-shape' warning."""
        amt = AMTResult(
            market_state="BALANCED", poc=100, value_area_high=105,
            value_area_low=95, profile_shape="b",
        )
        prompt = build_overseer_prompt(_pos_state(), _tick(), amt)
        assert "b-shape" in prompt.lower()
        assert "avoid short" in prompt.lower()

    def test_prompt_includes_stacked_imbalances(self):
        """Footprint with stacked levels -> prompt contains imbalance text."""
        # Create footprint candle with stacked imbalance levels
        class DummyFPLevel:
            def __init__(self, stacked=False): self.stacked = stacked
            
        class DummyFPCandle:
            def __init__(self, levels): self.levels = levels

        levels = [DummyFPLevel(stacked=True) for _ in range(4)]
        fp = DummyFPCandle(levels=levels)
        prompt = build_overseer_prompt(_pos_state(), _tick(), _amt(), footprint_candle=fp)
        assert "Stacked imbalances" in prompt

    def test_prompt_includes_lvn_play(self):
        """AMTResult with lvn_play -> prompt contains LVN play info."""
        amt = AMTResult(
            market_state="BALANCED", poc=100, value_area_high=105,
            value_area_low=95,
            lvn_play="LONG at 98 (target 103)",
        )
        prompt = build_overseer_prompt(_pos_state(), _tick(), amt)
        assert "LVN PLAY" in prompt
        assert "LONG" in prompt

    def test_missing_sources_no_crash(self):
        """All optional params None -> prompt still valid, no crash."""
        prompt = build_overseer_prompt(_pos_state(), _tick(), _amt())
        assert isinstance(prompt, str)
        assert "Open LONG" in prompt
        assert "JSON" in prompt

    def test_existing_overseer_prompt_unchanged(self):
        """Without new params, prompt output contains core sections."""
        prompt_new = build_overseer_prompt(_pos_state(), _tick(), _amt())
        assert "Open LONG position" in prompt_new
        assert "Market state:" in prompt_new
        assert "JSON" in prompt_new
