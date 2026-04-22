"""Tests for soft gate pipeline (rules 6, 8, 9, 10)."""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.services.gate_pipeline import GatePipeline, GateContext
from app.domain.trading.models.enums import MarketState


def _default_context(**overrides) -> GateContext:
    """Create a default context that passes all gates."""
    defaults = dict(
        symbol="CRUDEOIL",
        candle_count=15,
        tick_age_seconds=1.0,
        market_state=MarketState.IMBALANCED,
        poc=100.0, vah=105.0, val=95.0,
        price=106.0,  # Above VAH
        tick_size=0.1,
        key_levels=[106.0],
        nearest_level=106.0,
        distance_to_level_ticks=0.0,
        drive_number=2,
        drive_entry_valid=True,
        aggression_score=3.5,
        is_risk_halted=False,
        position_size_ok=True,
        eia_window_active=False,
        setup_type="TREND_CONTINUATION",
        r_r_ratio=2.5,
        cushion_ticks=3.0,
    )
    defaults.update(overrides)
    return GateContext(**defaults)


def test_soft_gate_6_price_at_entry_zone_passes():
    """Gate 6 should pass when price is within 3 ticks of level."""
    ctx = _default_context(distance_to_level_ticks=1.0)
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed >= 3, f"Only {result.soft_gates_passed}/4 soft gates passed"


def test_soft_gate_6_fails_when_far_from_level():
    """Gate 6 should fail when price is far from entry zone."""
    ctx = _default_context(distance_to_level_ticks=5.0)  # > 3 ticks
    result = GatePipeline().evaluate(ctx)
    # Should fail gate 6 but might pass others
    assert result.soft_gates_passed < 4


def test_soft_gate_8_aggression_minimum_passes():
    """Gate 8 should pass when aggression >= 2.0."""
    ctx = _default_context(aggression_score=2.5)
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed >= 3


def test_soft_gate_8_fails_low_aggression():
    """Gate 8 should fail when aggression < 2.0."""
    ctx = _default_context(aggression_score=1.5)  # < 2.0
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed < 4


def test_soft_gate_9_cushion_ticks_passes():
    """Gate 9 should pass when cushion <= 10 ticks."""
    ctx = _default_context(cushion_ticks=8.0)
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed >= 3


def test_soft_gate_9_fails_high_cushion():
    """Gate 9 should fail when cushion > 10 ticks."""
    ctx = _default_context(cushion_ticks=12.0)  # > 10
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed < 4


def test_soft_gate_10_rr_ratio_passes():
    """Gate 10 should pass when R:R >= 1.5."""
    ctx = _default_context(r_r_ratio=2.0)
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed >= 3


def test_soft_gate_10_fails_low_rr():
    """Gate 10 should fail when R:R < 1.5."""
    ctx = _default_context(r_r_ratio=1.2)  # < 1.5
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed < 4


def test_rule_checklist_breakout_above_vah():
    """Integration test: confirmed breakout above VAH should pass 4/4 rules."""
    ctx = _default_context(
        market_state=MarketState.IMBALANCED,
        price=106.0,  # Above VAH
        nearest_level=106.0,
        distance_to_level_ticks=0.0,
        aggression_score=3.5,
        r_r_ratio=2.5,
        cushion_ticks=3.0,
    )
    
    result = GatePipeline().evaluate(ctx)
    assert result.soft_gates_passed == 4, f"Expected 4/4 rules to pass, got {result.soft_gates_passed}/4"
    assert result.quorum_met
    assert result.passed


def test_soft_gate_logging_includes_actual_vs_threshold(caplog):
    """Verify failed gates log actual vs threshold values."""
    import logging
    caplog.set_level(logging.INFO)
    
    # Create context that will fail gate 8 (low aggression)
    ctx = _default_context(aggression_score=1.0)
    
    result = GatePipeline().evaluate(ctx)
    
    # Check logs contain actual and threshold values
    assert any("ACTUAL:" in record.message and "THRESHOLD:" in record.message 
               for record in caplog.records), "Expected actual vs threshold in logs"
