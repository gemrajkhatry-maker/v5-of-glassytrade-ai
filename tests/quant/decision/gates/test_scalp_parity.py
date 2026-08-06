"""Parity: evaluate_scalp_gates via legacy shim vs moved quant module."""

from __future__ import annotations

from app.domain.services.scalp_gate_pipeline import (
    ScalpContext as LegacyScalpContext,
    evaluate_scalp_gates as legacy_evaluate,
)
from quant.decision.gates.scalp import (
    ScalpContext,
    evaluate_scalp_gates,
)
from tests.quant.parity import assert_parity


def test_evaluate_scalp_gates_all_pass_parity():
    ctx = ScalpContext(
        symbol="NIFTY",
        current_time="10:30:00",
        mtf_bias="BULLISH",
        distance_to_level_ticks=5.0,
        risk_tier="NORMAL",
        portfolio_utilization=0.5,
        open_positions=2,
        position_size=100.0,
    )
    assert_parity(legacy_evaluate, evaluate_scalp_gates, ctx)


def test_evaluate_scalp_gates_default_parity():
    assert_parity(legacy_evaluate, evaluate_scalp_gates, ScalpContext(symbol="NIFTY"))


def test_evaluate_scalp_gates_blocked_parity():
    ctx = ScalpContext(
        symbol="NIFTY",
        current_time="22:00:00",
        mtf_bias="NEUTRAL",
        distance_to_level_ticks=20.0,
        risk_tier="DEFENSIVE",
        portfolio_utilization=0.9,
        open_positions=1,
        position_size=10.0,
    )
    assert_parity(legacy_evaluate, evaluate_scalp_gates, ctx)
