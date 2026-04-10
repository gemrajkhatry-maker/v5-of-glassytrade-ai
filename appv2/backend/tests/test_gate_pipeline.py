"""Tests for Gate Pipeline."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from appv2.domain.services.gate_pipeline import (
    GateContext,
    run_gate_pipeline,
    gate_session_warmup,
    gate_data_quality,
    soft_gate_aggression,
)


def test_all_gates_pass():
    """With good conditions, all gates should pass."""
    ctx = GateContext(
        session_phase="PRIMARY",
        market_state="BALANCED",
        data_candles=50,
        is_risk_halted=False,
        price=100.0,
        entry_zone=99.0,
        aggression_score=3.0,
        opposing_level=105.0,  # Within cushion (10 ticks × 0.05 = 0.5 → dist 5.0, which is > 0.5)
        r_r_ratio=2.0,
        tick_age_seconds=5,
        profile_shape="D",
        cvd_slope=1.0,
        tick_size=0.05,
    )
    # For soft gates: need 3/4 to pass
    # EntryZone: |100-99|=1.0 > 3×0.05=0.15 → FAIL
    # Aggression: 3.0 >= 2.0 → PASS
    # Cushion: |100-105|=5.0 > 10×0.05=0.5 → FAIL
    # RR: 2.0 >= 1.5 → PASS
    # 2/4 passes < 3 quorum → need to adjust test
    # Make entry_zone and cushion pass
    ctx.entry_zone = 100.0  # Price at entry zone → PASS
    ctx.opposing_level = 100.4  # Distance 0.4 < 10×0.05=0.5 → PASS

    passed, reason, detail = run_gate_pipeline(ctx)
    assert passed, f"Should pass: {reason} - {detail}"


def test_session_warmup_rejects():
    """Opening phase should reject."""
    ctx = GateContext(session_phase="OPENING")
    result = gate_session_warmup(ctx)
    assert not result.passed


def test_insufficient_data_rejects():
    """Less than 5 candles should reject."""
    ctx = GateContext(data_candles=3)
    result = gate_data_quality(ctx)
    assert not result.passed


def test_low_aggression_soft_gate():
    """Low aggression score should fail soft gate."""
    ctx = GateContext(aggression_score=0.5)
    result = soft_gate_aggression(ctx)
    assert not result.passed


def test_risk_halt_rejects():
    """Risk halt should hard-reject."""
    ctx = GateContext(
        session_phase="PRIMARY",
        market_state="BALANCED",
        data_candles=50,
        is_risk_halted=True,
        price=100.0,
        entry_zone=99.0,
        aggression_score=3.0,
        opposing_level=110.0,
        r_r_ratio=2.0,
        tick_age_seconds=5,
        tick_size=0.05,
    )

    passed, reason, detail = run_gate_pipeline(ctx)
    assert not passed
    assert "RiskHalt" in reason or reason == "RiskHalt"
