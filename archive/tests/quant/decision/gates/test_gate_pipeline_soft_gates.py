"""Tests for the strategy-quality checks folded into the 5-gate pipeline.

The old soft gates (6 proximity, 8 aggression, 9 cushion, 10 R:R) are folded:
  - proximity / level-location → GATE 4 (strategy alignment)
  - IMBALANCED probing aggression → GATE 2 (no-position/cooldown)
  - cushion + R:R → GATE 5 (risk-reward)

There is no soft-gate quorum anymore — every gate is fail-fast.
"""

from __future__ import annotations

import pytest

from quant.decision.gates.legacy_gate_pipeline import GatePipeline, GateContext
from quant.contracts.enums import MarketState


def _default_context(**overrides) -> GateContext:
    """Create a default context that passes all 5 gates."""
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
        absorption_detected=True,
        absorption_bar_age=0,
        vwap_breakout=None,
    )
    defaults.update(overrides)
    return GateContext(**defaults)


def test_gate_4_price_at_entry_zone_passes():
    """Price within max ticks of a level passes gate 4."""
    ctx = _default_context(distance_to_level_ticks=1.0)
    result = GatePipeline().evaluate(ctx)
    assert result.passed is True


def test_gate_4_fails_when_far_from_level():
    """Distance-to-level (old soft gate 6) folds into gate 4 (WAIT)."""
    ctx = _default_context(distance_to_level_ticks=5.0)  # > 3 ticks
    result = GatePipeline().evaluate(ctx)
    assert result.passed is False
    assert result.gate == 4
    assert result.soft_gates_passed == 3  # gates 1-3 passed


def test_gate_2_imbalanced_requires_aggression():
    """IMBALANCED probing without high aggression blocks gate 2 (FLAT)."""
    ctx = _default_context(aggression_score=1.5)  # < probing threshold
    result = GatePipeline().evaluate(ctx)
    assert result.passed is False
    assert result.gate == 2
    assert result.reason.value == "FLAT"


def test_imbalanced_with_aggression_passes():
    ctx = _default_context(aggression_score=3.5, market_state=MarketState.BALANCED)
    result = GatePipeline().evaluate(ctx)
    assert result.passed is True


def test_gate_5_cushion_ticks_passes():
    ctx = _default_context(cushion_ticks=8.0)
    result = GatePipeline().evaluate(ctx)
    assert result.passed is True


def test_gate_5_fails_high_cushion():
    """Cushion > max ticks (old soft gate 9) folds into gate 5 (INVALID)."""
    ctx = _default_context(cushion_ticks=12.0)  # > 10
    result = GatePipeline().evaluate(ctx)
    assert result.passed is False
    assert result.gate == 5
    assert result.reason.value == "INVALID"
    assert result.gate_count == 5


def test_gate_5_rr_ratio_passes():
    ctx = _default_context(r_r_ratio=2.0)
    result = GatePipeline().evaluate(ctx)
    assert result.passed is True


def test_gate_5_fails_low_rr():
    """R:R < 1.5 (old soft gate 10) is now a hard gate 5 (SKIP)."""
    ctx = _default_context(r_r_ratio=1.2)  # < 1.5
    result = GatePipeline().evaluate(ctx)
    assert result.passed is False
    assert result.gate == 5
    assert result.reason.value == "SKIP"
    assert result.gate_count == 5


def test_breakout_above_vah_passes_all_five():
    """Confirmed breakout above VAH with an AGGRESSION edge passes 5/5."""
    ctx = _default_context(
        market_state=MarketState.IMBALANCED,
        price=106.0,  # Above VAH
        nearest_level=106.0,
        distance_to_level_ticks=0.0,
        aggression_score=3.5,
        r_r_ratio=2.5,
        cushion_ticks=3.0,
        absorption_detected=True,
        absorption_bar_age=0,
    )

    result = GatePipeline().evaluate(ctx)
    assert result.passed is True
    assert result.reason.value == "TRADE"
    assert result.soft_gates_passed == 5
    assert result.gate_count == 5


def test_gate_failures_log_gate_number(caplog):
    """Verify failed gates log the gate number."""
    import logging

    caplog.set_level(logging.DEBUG)
    ctx = _default_context(r_r_ratio=1.2)
    GatePipeline().evaluate(ctx)
    assert any("GATE FAILED" in record.message for record in caplog.records)
