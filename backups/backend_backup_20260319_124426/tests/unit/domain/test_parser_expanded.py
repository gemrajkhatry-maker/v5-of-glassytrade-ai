"""Expanded parser tests covering all model output vocabulary patterns.

Tests the two-stage _parse_response() in GenerativeAIService against:
- All 8 training trigger patterns
- Creative model output variations discovered in vocabulary mapping
- Confidence extraction
- FLAT detection for risk management
- Unknown output warning logging
"""

import pytest
import logging

from app.domain.fabio_ai.services.prompt_builder import parse_entry_response


# ---------------------------------------------------------------
# Stage 1: Trigger line extraction — LONG
# ---------------------------------------------------------------

class TestTriggerLong:
    def test_enter_long_basic(self):
        r = parse_entry_response("Market State: **Balance**. Logic: **AAA Setup**. Trigger: **Enter Long**. Stop: Below VAL.")
        assert r["direction"] == "LONG"

    def test_enter_long_on_pullback(self):
        r = parse_entry_response("Trigger: **Enter Long** on pullback to the **Protection Level** (where big buyers stepped in).")
        assert r["direction"] == "LONG"

    def test_enter_long_on_reentry(self):
        r = parse_entry_response("Trigger: **Enter Long** on re-entry into Value. Target: VAH.")
        assert r["direction"] == "LONG"

    def test_long_with_size(self):
        r = parse_entry_response("Logic: **AAA Setup**. Trigger: **Long** with size. Target: Rotation to top.")
        assert r["direction"] == "LONG"

    def test_long_on_any_dip(self):
        r = parse_entry_response("Trigger: **Long** on any dip. Do not fade. Target: Session Highs.")
        assert r["direction"] == "LONG"

    def test_add_to_longs(self):
        r = parse_entry_response("Trigger: **Add to Longs** risk-free. Stop: Below protection wall.")
        assert r["direction"] == "LONG"

    def test_enter_long_with_full_allocation(self):
        r = parse_entry_response("Trigger: **Enter Long** with full allocation. Stop: Below absorption.")
        assert r["direction"] == "LONG"

    def test_long_on_pullback_to_vah(self):
        r = parse_entry_response("Trigger: **Long** on pullback to VAH/SGT. Target: Extension.")
        assert r["direction"] == "LONG"

    def test_reenter_long(self):
        r = parse_entry_response("Trigger: **Re-enter Long** when price breaks through the absorption level.")
        assert r["direction"] == "LONG"

    def test_enter_long_at_price(self):
        r = parse_entry_response("Trigger: **Enter Long** at 14929. Stop tight.")
        assert r["direction"] == "LONG"

    def test_long_with_target(self):
        r = parse_entry_response("Trigger: **Long** with target 65458 (VAH). Stop below POC.")
        assert r["direction"] == "LONG"


# ---------------------------------------------------------------
# Stage 1: Trigger line extraction — SHORT
# ---------------------------------------------------------------

class TestTriggerShort:
    def test_enter_short_basic(self):
        r = parse_entry_response("Market State: **Failed Auction**. Trigger: **Enter Short**. Target: VAL.")
        assert r["direction"] == "SHORT"

    def test_short_on_confirmation(self):
        r = parse_entry_response("Trigger: **Short** on confirmation of rotation back inside. Focus: Target middle.")
        assert r["direction"] == "SHORT"

    def test_short_with_target(self):
        r = parse_entry_response("Trigger: **Short** with target: **15115** (order block).")
        assert r["direction"] == "SHORT"

    def test_short_with_target_val(self):
        r = parse_entry_response("Trigger: **Short** with target: breakthrough of value area low (14997).")
        assert r["direction"] == "SHORT"

    def test_enter_short_on_pullback(self):
        r = parse_entry_response("Trigger: **Enter Short** on a pullback to **15033** (or any value area boundary).")
        assert r["direction"] == "SHORT"


# ---------------------------------------------------------------
# Stage 2: Logic fallback
# ---------------------------------------------------------------

class TestLogicFallback:
    def test_aaa_setup_implies_long(self):
        """When Trigger line is missing but Logic says AAA Setup."""
        r = parse_entry_response("Market State: **Balance**. Logic: **AAA Setup**. Passive buyers holding.")
        assert r["direction"] == "LONG"

    def test_momentum_continuation_implies_long(self):
        r = parse_entry_response("Logic: **Momentum Continuation**. Buyers in full control.")
        assert r["direction"] == "LONG"

    def test_momentum_squeeze_implies_short(self):
        r = parse_entry_response("Logic: **Momentum Squeeze**. Sellers pressing down.")
        assert r["direction"] == "SHORT"

    def test_breakout_failed_implies_short(self):
        r = parse_entry_response("Logic: Breakout failed. Aggressive buyers are trapped.")
        assert r["direction"] == "SHORT"

    def test_buyers_exhausted_implies_short(self):
        r = parse_entry_response("Logic: Buyers exhausted. Punching a wall. Price failing.")
        assert r["direction"] == "SHORT"

    def test_buyers_trapped_implies_short(self):
        r = parse_entry_response("Logic: Buyers are trapped at highs. Market rotating lower.")
        assert r["direction"] == "SHORT"


# ---------------------------------------------------------------
# FLAT detection
# ---------------------------------------------------------------

class TestFlat:
    def test_stay_flat_explicit(self):
        r = parse_entry_response("Trigger: **Stay Flat**. Rule: No setup.")
        assert r["direction"] == "FLAT"

    def test_walk_away(self):
        r = parse_entry_response("Logic: **Risk Management**. Walk away. Don't overtrade.")
        assert r["direction"] == "FLAT"

    def test_bank_profit(self):
        r = parse_entry_response("Logic: **Bank Profit**. Take partials or close.")
        assert r["direction"] == "FLAT"

    def test_stop_trading(self):
        r = parse_entry_response("Logic: **Discipline**. Stop trading or reduce size.")
        assert r["direction"] == "FLAT"

    def test_take_profit(self):
        r = parse_entry_response("Trigger: **Take Profit**. Close position now.")
        assert r["direction"] == "FLAT"

    def test_risk_management(self):
        r = parse_entry_response("Logic: **Risk Management**. No edge in current conditions.")
        assert r["direction"] == "FLAT"


# ---------------------------------------------------------------
# Confidence extraction
# ---------------------------------------------------------------

class TestConfidence:
    def test_high_confidence_with_size(self):
        r = parse_entry_response("Trigger: **Long** with size. Target: VAH.")
        assert r["confidence"] == "High"

    def test_high_confidence_squeeze(self):
        r = parse_entry_response("Trigger: **Enter Long** on squeeze. Full allocation.")
        assert r["confidence"] == "High"

    def test_medium_confidence_default(self):
        r = parse_entry_response("Trigger: **Enter Long**. Stop: Below VAL.")
        assert r["confidence"] == "Medium"

    def test_low_confidence_wait(self):
        r = parse_entry_response("Trigger: **Wait for Break** above session high.")
        # This should parse as FLAT (no directional trigger)
        assert r["direction"] == "FLAT"


# ---------------------------------------------------------------
# Real model outputs from vocabulary mapping
# ---------------------------------------------------------------

class TestRealModelOutputs:
    def test_short_setup_trigger(self):
        """Model output: 'Logic: **Short Setup**. Trigger: **Absorption/Breakdown**'"""
        r = parse_entry_response(
            "Logic: **Short Setup**. Trigger: **Absorption/Breakdown** into VA Lows (<14987). "
            "Stop: Tight above float. Target: VWAP / Session Close."
        )
        # This doesn't contain explicit short trigger words — model limitation
        # But it shouldn't false-positive as LONG either
        assert r["direction"] in ("SHORT", "FLAT")

    def test_timing_wait(self):
        r = parse_entry_response(
            "Logic: **Timing**. We are waiting for a trigger. Do not waste effort "
            "pricing into a wall. Wait for rotation."
        )
        assert r["direction"] == "FLAT"

    def test_long_into_tighter_high(self):
        r = parse_entry_response("Trigger: **Long** into a tighter high. Target: Extension.")
        assert r["direction"] == "LONG"

    def test_momentum_squeeze_long(self):
        r = parse_entry_response(
            "Market State: **Imbalance** (Trend). Logic: **Momentum Squeeze**. "
            "Trigger: **Enter Long** on pullback to the **Protection Level**."
        )
        assert r["direction"] == "LONG"

    def test_short_covering_long(self):
        r = parse_entry_response(
            "Logic: **Short Covering Opportunity**. Trigger: **Long** on any dip below the pivot level."
        )
        assert r["direction"] == "LONG"


# ---------------------------------------------------------------
# Edge cases & backward compatibility
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self):
        r = parse_entry_response("")
        assert r["direction"] == "FLAT"

    def test_gibberish(self):
        r = parse_entry_response("asdfghjkl random text nothing useful")
        assert r["direction"] == "FLAT"

    def test_case_insensitive(self):
        r = parse_entry_response("TRIGGER: **ENTER LONG**. TARGET: VAH.")
        assert r["direction"] == "LONG"

    def test_model_loading_message(self):
        r = parse_entry_response("Analysis Warning: Model is still loading...")
        assert r["direction"] == "FLAT"

    def test_error_message(self):
        r = parse_entry_response("Analysis Error: Model failed to load.")
        assert r["direction"] == "FLAT"

    def test_unparsed_output_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            parse_entry_response("Some completely unexpected model output format")
        assert "Unparsed model output" in caplog.text
