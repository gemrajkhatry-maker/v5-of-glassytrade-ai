"""Unit tests for RuleBasedRationale — deterministic trade explanation per FR-11."""

import pytest
from app.domain.fabio_ai.services.rule_based_rationale import (
    RuleBasedRationale,
    RationaleContext,
)


def _ctx(direction="LONG", market_state="BALANCED", zone="NEAR_VAL",
        poc=100, vah=105, val=95, price=96,
        aggression_score=3.0, aggression_confidence="HIGH",
        footprint_confirmed=True, cvd_confirmed=True,
        big_trade_confirmed=False, absorption_detected=False,
        ofi_aligned=False, confluence_bonus=False, volume_bubble_near=False,
        cvd_slope=0.5, cvd_divergence="",
        drive_number=2, drive_level=95,
        setup_type="MEAN_REVERSION", entry_price=96, stop_loss=94,
        take_profit=100, r_r_ratio=2.0, gate_number=12,
        profile_shape="b", lvn_play=None):
    return RationaleContext(
        market_state=market_state, zone=zone,
        poc=poc, vah=vah, val=val, price=price,
        aggression_score=aggression_score,
        aggression_confidence=aggression_confidence,
        footprint_confirmed=footprint_confirmed,
        cvd_confirmed=cvd_confirmed,
        big_trade_confirmed=big_trade_confirmed,
        absorption_detected=absorption_detected,
        ofi_aligned=ofi_aligned,
        confluence_bonus=confluence_bonus,
        volume_bubble_near=volume_bubble_near,
        cvd_slope=cvd_slope, cvd_divergence=cvd_divergence,
        drive_number=drive_number, drive_level=drive_level,
        direction=direction, setup_type=setup_type,
        entry_price=entry_price, stop_loss=stop_loss,
        take_profit=take_profit, r_r_ratio=r_r_ratio,
        gate_number=gate_number, profile_shape=profile_shape,
        lvn_play=lvn_play,
    )


class TestRuleBasedRationaleGenerate:
    """Test rationale generation for trade signals."""

    def test_long_mean_reversion_rationale(self):
        """LONG mean reversion setup generates correct rationale."""
        gen = RuleBasedRationale()
        ctx = _ctx(direction="LONG", setup_type="MEAN_REVERSION")
        rationale = gen.generate(ctx)
        assert "BALANCED" in rationale
        assert "NEAR_VAL" in rationale
        assert "Mean Reversion" in rationale
        assert "LONG" in rationale
        assert "R:R" in rationale

    def test_short_trend_rationale(self):
        """SHORT trend setup generates correct rationale."""
        gen = RuleBasedRationale()
        ctx = _ctx(direction="SHORT", setup_type="TREND_MODEL",
                   price=104, zone="NEAR_VAH", entry_price=104, stop_loss=106,
                   take_profit=95, drive_number=2, drive_level=105)
        rationale = gen.generate(ctx)
        assert "Trend" in rationale
        assert "SHORT" in rationale
        assert "VAH" in rationale

    def test_aggression_breakdown_in_rationale(self):
        """Aggression breakdown shows active signals."""
        gen = RuleBasedRationale()
        ctx = _ctx(footprint_confirmed=True, cvd_confirmed=True,
                   big_trade_confirmed=True, absorption_detected=True)
        rationale = gen.generate(ctx)
        assert "footprint imbalance" in rationale
        assert "CVD aligned" in rationale
        assert "institutional prints" in rationale
        assert "absorption" in rationale

    def test_drive_context_included(self):
        """Drive context included when drive_number >= 2."""
        gen = RuleBasedRationale()
        ctx = _ctx(drive_number=2, drive_level=95)
        rationale = gen.generate(ctx)
        assert "Second drive" in rationale
        assert "95.00" in rationale

    def test_lvn_play_included(self):
        """LVN play context included when present."""
        gen = RuleBasedRationale()
        ctx = _ctx(lvn_play={"direction": "LONG", "price": 95.5})
        rationale = gen.generate(ctx)
        assert "LVN play" in rationale
        assert "95.50" in rationale


class TestRuleBasedRationaleFlat:
    """Test rationale for FLAT decisions."""

    def test_no_trade_state(self):
        """NO_TRADE state generates correct rationale."""
        gen = RuleBasedRationale()
        ctx = _ctx(direction="FLAT", market_state="NO_TRADE")
        rationale = gen.generate(ctx)
        assert "NO_TRADE" in rationale
        assert "POC" in rationale

    def test_probing_state(self):
        """PROBING state generates correct rationale."""
        gen = RuleBasedRationale()
        ctx = _ctx(direction="FLAT", market_state="PROBING")
        rationale = gen.generate(ctx)
        assert "PROBING" in rationale

    def test_insufficient_aggression(self):
        """Low aggression generates correct rationale."""
        gen = RuleBasedRationale()
        ctx = _ctx(direction="FLAT", aggression_score=1.5)
        rationale = gen.generate(ctx)
        assert "1.5" in rationale
        assert "2.0" in rationale

    def test_low_rr(self):
        """Low R:R generates correct rationale."""
        gen = RuleBasedRationale()
        ctx = _ctx(direction="FLAT", r_r_ratio=1.2, aggression_score=3.0,
                   market_state="BALANCED")
        rationale = gen.generate(ctx)
        assert "1.20" in rationale
        assert "1.5" in rationale


class TestRuleBasedRationaleMarketNarrative:
    """Test market narrative generation."""

    def test_balance_to_imbalance(self):
        gen = RuleBasedRationale()
        narrative = gen.generate_market_narrative(
            prev_state="BALANCED", curr_state="IMBALANCED",
            poc=100, vah=105, val=95, price=106,
        )
        assert "BALANCE" in narrative
        assert "IMBALANCE" in narrative
        assert "displacement" in narrative

    def test_imbalance_to_balance(self):
        gen = RuleBasedRationale()
        narrative = gen.generate_market_narrative(
            prev_state="IMBALANCED", curr_state="BALANCED",
            poc=100, vah=105, val=95, price=100,
        )
        assert "BALANCE" in narrative
        assert "fading" in narrative

    def test_balance_to_probing(self):
        gen = RuleBasedRationale()
        narrative = gen.generate_market_narrative(
            prev_state="BALANCED", curr_state="PROBING",
            poc=100, vah=105, val=95, price=106,
        )
        assert "PROBING" in narrative
        assert "confirmation" in narrative


class TestRuleBasedRationaleRiskCommentary:
    """Test risk commentary generation."""

    def test_consecutive_losses(self):
        gen = RuleBasedRationale()
        commentary = gen.generate_risk_commentary(
            event_type="CONSECUTIVE_LOSSES",
            consecutive_losses=3,
            daily_pnl=-1500.0,
            max_drawdown=0.025,
        )
        assert "3" in commentary
        assert "-1500" in commentary
        assert "2.50%" in commentary

    def test_daily_loss_limit(self):
        gen = RuleBasedRationale()
        commentary = gen.generate_risk_commentary(
            event_type="DAILY_LOSS_LIMIT",
            consecutive_losses=2,
            daily_pnl=-2000.0,
            max_drawdown=0.02,
        )
        assert "Daily loss limit" in commentary
        assert "paused" in commentary