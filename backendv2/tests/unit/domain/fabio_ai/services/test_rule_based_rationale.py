"""Tests for rule_based_rationale.py — deterministic rationale generation."""
from __future__ import annotations

from app.domain.fabio_ai.services.rule_based_rationale import (
    RationaleContext,
    RuleBasedRationale,
)


def _make_ctx(**overrides):
    defaults = {
        "market_state": "BALANCED",
        "zone": "AT_POC",
        "poc": 100.0,
        "vah": 105.0,
        "val": 95.0,
        "price": 100.0,
        "aggression_score": 3.0,
        "aggression_confidence": "Medium",
        "footprint_confirmed": True,
        "cvd_confirmed": True,
        "big_trade_confirmed": False,
        "absorption_detected": False,
        "ofi_aligned": True,
        "confluence_bonus": False,
        "volume_bubble_near": False,
        "cvd_slope": 0.5,
        "cvd_divergence": "",
        "drive_number": 1,
        "drive_level": 0.0,
        "direction": "LONG",
        "setup_type": "TREND_MODEL",
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 106.0,
        "r_r_ratio": 3.0,
        "gate_number": 0,
        "profile_shape": "B",
        "lvn_play": None,
        "vwap": 99.0,
        "vwap_bias": "above",
    }
    defaults.update(overrides)
    return RationaleContext(**defaults)


class TestGenerateFlat:
    """Tests for FLAT direction rationale."""

    def test_low_rr_explains_too_low(self):
        """When R:R < 1.5, explains R:R too low."""
        ctx = _make_ctx(direction="FLAT", r_r_ratio=1.2)
        rationale = RuleBasedRationale().generate(ctx)
        assert "too low" in rationale.lower()
        assert "1.20" in rationale

    def test_low_aggression_explains_insufficient(self):
        """When aggression < 2.0, explains insufficient aggression."""
        ctx = _make_ctx(direction="FLAT", r_r_ratio=2.0, aggression_score=1.5)
        rationale = RuleBasedRationale().generate(ctx)
        assert "insufficient aggression" in rationale.lower()
        assert "1.5" in rationale

    def test_no_edge_returns_generic(self):
        """When R:R and aggression are fine, returns no high-confidence edge."""
        ctx = _make_ctx(direction="FLAT", r_r_ratio=2.0, aggression_score=3.0)
        rationale = RuleBasedRationale().generate(ctx)
        assert "No high-confidence" in rationale


class TestGenerateDirectional:
    """Tests for LONG/SHORT direction rationale."""

    def test_long_produces_complete_rationale(self):
        """LONG direction produces market state + level + aggression + setup."""
        ctx = _make_ctx(direction="LONG")
        rationale = RuleBasedRationale().generate(ctx)
        assert "LONG" in rationale
        assert "Trend" in rationale
        assert "entry 100.00" in rationale

    def test_short_produces_complete_rationale(self):
        """SHORT direction produces complete rationale."""
        ctx = _make_ctx(direction="SHORT")
        rationale = RuleBasedRationale().generate(ctx)
        assert "SHORT" in rationale

    def test_mean_reversion_setup(self):
        """MEAN_REVERSION setup shows 'Mean Reversion' in rationale."""
        ctx = _make_ctx(direction="LONG", setup_type="MEAN_REVERSION")
        rationale = RuleBasedRationale().generate(ctx)
        assert "Mean Reversion" in rationale


class TestMarketStateSentence:
    """Tests for _market_state_sentence()."""

    def test_imbalanced_shows_outside_va(self):
        """IMBALANCED market shows price outside VA."""
        ctx = _make_ctx(market_state="IMBALANCED", price=110.0, val=95.0, vah=105.0)
        result = RuleBasedRationale()._market_state_sentence(ctx)
        assert "IMBALANCED" in result
        assert "outside VA" in result

    def test_balanced_shows_near_va(self):
        """BALANCED market shows price near VA."""
        ctx = _make_ctx(market_state="BALANCED", price=100.0, val=95.0, vah=105.0, zone="AT_POC")
        result = RuleBasedRationale()._market_state_sentence(ctx)
        assert "BALANCED" in result
        assert "near VA" in result

    def test_other_state_shows_raw(self):
        """Unknown market state shows raw state name."""
        ctx = _make_ctx(market_state="DEAD")
        result = RuleBasedRationale()._market_state_sentence(ctx)
        assert "DEAD" in result


class TestKeyLevelSentence:
    """Tests for _key_level_sentence()."""

    def test_price_at_poc(self):
        """When price is very close to POC, reports at POC."""
        ctx = _make_ctx(price=100.05, poc=100.0, vah=105.0, val=95.0)
        result = RuleBasedRationale()._key_level_sentence(ctx)
        assert "POC" in result
        assert "at" in result.lower()

    def test_price_far_from_levels(self):
        """When price is far, reports distance to nearest."""
        ctx = _make_ctx(price=150.0, poc=100.0, vah=105.0, val=95.0)
        result = RuleBasedRationale()._key_level_sentence(ctx)
        assert "Nearest level" in result or "away" in result


class TestAggressionSentence:
    """Tests for _aggression_sentence()."""

    def test_lists_confirmations(self):
        """Lists all confirmed aggression components."""
        ctx = _make_ctx(
            footprint_confirmed=True, cvd_confirmed=True, big_trade_confirmed=True,
            absorption_detected=True, ofi_aligned=True, confluence_bonus=True,
            volume_bubble_near=True,
        )
        result = RuleBasedRationale()._aggression_sentence(ctx)
        assert "footprint imbalance" in result
        assert "CVD" in result
        assert "institutional prints" in result
        assert "absorption" in result
        assert "OFI aligned" in result
        assert "confluence" in result
        assert "volume bubble" in result

    def test_no_confirmations_shows_score(self):
        """When no confirmations, shows just score and confidence."""
        ctx = _make_ctx(
            footprint_confirmed=False, cvd_confirmed=False, big_trade_confirmed=False,
            absorption_detected=False, ofi_aligned=False, confluence_bonus=False,
            volume_bubble_near=False, aggression_score=2.5, aggression_confidence="Medium",
        )
        result = RuleBasedRationale()._aggression_sentence(ctx)
        assert "2.5" in result
        assert "Medium" in result

    def test_cvd_divergence_in_sentence(self):
        """CVD divergence is included in aggression sentence."""
        ctx = _make_ctx(cvd_confirmed=True, cvd_divergence="BULLISH_DIV")
        result = RuleBasedRationale()._aggression_sentence(ctx)
        assert "bullish_div" in result.lower()


class TestSetupSentence:
    """Tests for _setup_sentence()."""

    def test_trend_model_shows_trend(self):
        """TREND_MODEL setup shows 'Trend'."""
        ctx = _make_ctx(setup_type="TREND_MODEL")
        result = RuleBasedRationale()._setup_sentence(ctx)
        assert "Trend" in result

    def test_mean_reversion_shows_mean_reversion(self):
        """MEAN_REVERSION setup shows 'Mean Reversion'."""
        ctx = _make_ctx(setup_type="MEAN_REVERSION")
        result = RuleBasedRationale()._setup_sentence(ctx)
        assert "Mean Reversion" in result

    def test_shows_entry_sl_tp_rr(self):
        """Shows entry, SL, TP, and R:R values."""
        ctx = _make_ctx(entry_price=100.0, stop_loss=98.0, take_profit=106.0, r_r_ratio=3.0)
        result = RuleBasedRationale()._setup_sentence(ctx)
        assert "entry 100.00" in result
        assert "SL 98.00" in result
        assert "TP 106.00" in result
        assert "R:R 3.00" in result


class TestDriveSentence:
    """Tests for _drive_sentence()."""

    def test_drive_n_at_price(self):
        """Drive sentence shows drive number and level."""
        ctx = _make_ctx(drive_number=2, drive_level=101.0)
        result = RuleBasedRationale()._drive_sentence(ctx)
        assert "Drive 2" in result
        assert "101.00" in result


class TestLvnSentence:
    """Tests for _lvn_sentence()."""

    def test_lvn_play_included(self):
        """LVN play sentence shows direction and price."""
        ctx = _make_ctx(lvn_play={"direction": "LONG", "price": 99.5})
        result = RuleBasedRationale()._lvn_sentence(ctx)
        assert "LVN play" in result
        assert "LONG" in result
        assert "99.50" in result

    def test_no_lvn_returns_empty(self):
        """No LVN play returns empty string."""
        ctx = _make_ctx(lvn_play=None)
        result = RuleBasedRationale()._lvn_sentence(ctx)
        assert result == ""


class TestGenerateMarketNarrative:
    """Tests for generate_market_narrative()."""

    def test_state_transition_narrative(self):
        """Generates state transition narrative."""
        result = RuleBasedRationale().generate_market_narrative(
            "BALANCED", "IMBALANCED", 100.0, 105.0, 95.0, 110.0
        )
        assert "BALANCED" in result
        assert "IMBALANCED" in result
        assert "100.00" in result
        assert "95.00-105.00" in result


class TestGenerateRiskCommentary:
    """Tests for generate_risk_commentary()."""

    def test_consecutive_losses(self):
        """Consecutive losses commentary."""
        result = RuleBasedRationale().generate_risk_commentary(
            "CONSECUTIVE_LOSSES", 3, -500.0, 0.05
        )
        assert "3 consecutive losses" in result

    def test_daily_loss_limit(self):
        """Daily loss limit hit commentary."""
        result = RuleBasedRationale().generate_risk_commentary(
            "DAILY_LOSS_LIMIT", 0, -1000.0, 0.0
        )
        assert "Daily loss limit" in result
        assert "paused" in result

    def test_drawdown_limit(self):
        """Drawdown limit hit commentary."""
        result = RuleBasedRationale().generate_risk_commentary(
            "DRAWDOWN_LIMIT", 0, -200.0, 0.10
        )
        assert "Max drawdown" in result
        assert "10.00%" in result

    def test_generic_risk_event(self):
        """Unknown event type returns generic message."""
        result = RuleBasedRationale().generate_risk_commentary(
            "UNKNOWN_EVENT", 0, 0.0, 0.0
        )
        assert "Risk event" in result
