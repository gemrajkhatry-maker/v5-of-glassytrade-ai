"""Tests for Scalp Gate Pipeline."""

import pytest
from app.domain.services.scalp_gate_pipeline import (
    ScalpGate,
    ScalpContext,
    ScalpGateResult,
    evaluate_scalp_gates,
)


class TestScalpGate:
    """Tests for ScalpGate enum."""

    def test_session_timing(self):
        assert ScalpGate.SESSION_TIMING.value == "SESSION_TIMING"

    def test_mtf_alignment(self):
        assert ScalpGate.MTF_ALIGNMENT.value == "MTF_ALIGNMENT"

    def test_level_proximity(self):
        assert ScalpGate.LEVEL_PROXIMITY.value == "LEVEL_PROXIMITY"

    def test_risk_tier(self):
        assert ScalpGate.RISK_TIER.value == "RISK_TIER"

    def test_portfolio_headroom(self):
        assert ScalpGate.PORTFOLIO_HEADROOM.value == "PORTFOLIO_HEADROOM"

    def test_no_double_exposure(self):
        assert ScalpGate.NO_DOUBLE_EXPOSURE.value == "NO_DOUBLE_EXPOSURE"


class TestScalpGateResult:
    """Tests for ScalpGateResult dataclass."""

    def test_create(self):
        """Test creating a ScalpGateResult."""
        result = ScalpGateResult(
            gate=ScalpGate.SESSION_TIMING,
            passed=True,
            detail="Session is active",
        )
        assert result.gate == ScalpGate.SESSION_TIMING
        assert result.passed is True
        assert result.detail == "Session is active"

    def test_defaults(self):
        """Test default values."""
        result = ScalpGateResult(
            gate=ScalpGate.MTF_ALIGNMENT,
        )
        assert result.passed is False
        assert result.detail == ""


class TestScalpContext:
    """Tests for ScalpContext dataclass."""

    def test_create(self):
        """Test creating a ScalpContext."""
        context = ScalpContext(
            symbol="NIFTY",
            current_time="10:30:00",
            mtf_bias="BULLISH",
            distance_to_level_ticks=5.0,
            risk_tier="NORMAL",
            portfolio_utilization=0.5,
            open_positions=2,
            position_size=100.0,
        )
        assert context.symbol == "NIFTY"
        assert context.mtf_bias == "BULLISH"
        assert context.distance_to_level_ticks == 5.0

    def test_defaults(self):
        """Test default values."""
        context = ScalpContext()
        assert context.symbol == ""
        assert context.mtf_bias == "NEUTRAL"
        assert context.distance_to_level_ticks == 0.0


class TestEvaluateScalpGates:
    """Tests for evaluate_scalp_gates function."""

    def test_returns_6_results(self):
        """Test that evaluate_scalp_gates returns 6 gate results."""
        context = ScalpContext(symbol="NIFTY")
        results = evaluate_scalp_gates(context)
        assert len(results) == 6

    def test_all_gates_pass(self):
        """Test that all gates pass (stub implementation)."""
        context = ScalpContext(
            symbol="NIFTY",
            current_time="10:30:00",
            mtf_bias="BULLISH",
            distance_to_level_ticks=5.0,
            risk_tier="NORMAL",
            portfolio_utilization=0.5,
            open_positions=2,
            position_size=100.0,
        )
        results = evaluate_scalp_gates(context)
        # All required gates pass under healthy scaffold conditions
        assert all(r.passed for r in results)

    def test_gate_types(self):
        """Test that all gate types are evaluated."""
        context = ScalpContext(symbol="NIFTY")
        results = evaluate_scalp_gates(context)
        gate_types = {r.gate for r in results}
        assert ScalpGate.SESSION_TIMING in gate_types
        assert ScalpGate.MTF_ALIGNMENT in gate_types
        assert ScalpGate.LEVEL_PROXIMITY in gate_types
        assert ScalpGate.RISK_TIER in gate_types
        assert ScalpGate.PORTFOLIO_HEADROOM in gate_types
        assert ScalpGate.NO_DOUBLE_EXPOSURE in gate_types

    def test_session_timing_gate(self):
        """Test session timing gate."""
        context = ScalpContext(
            symbol="NIFTY",
            current_time="10:30:00",
        )
        results = evaluate_scalp_gates(context)
        session_timing = next(
            r for r in results if r.gate == ScalpGate.SESSION_TIMING
        )
        assert session_timing.passed is True
        assert "session window" in session_timing.detail.lower()

    def test_mtf_alignment_gate(self):
        """Test MTF alignment gate."""
        context = ScalpContext(
            symbol="NIFTY",
            mtf_bias="BULLISH",
        )
        results = evaluate_scalp_gates(context)
        mtf_alignment = next(
            r for r in results if r.gate == ScalpGate.MTF_ALIGNMENT
        )
        assert mtf_alignment.passed is True

    def test_level_proximity_gate(self):
        """Test level proximity gate."""
        context = ScalpContext(
            symbol="NIFTY",
            distance_to_level_ticks=5.0,
        )
        results = evaluate_scalp_gates(context)
        level_proximity = next(
            r for r in results if r.gate == ScalpGate.LEVEL_PROXIMITY
        )
        assert level_proximity.passed is True
