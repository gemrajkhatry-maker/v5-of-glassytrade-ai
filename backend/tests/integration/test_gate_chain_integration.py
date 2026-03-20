"""Integration tests for GateChain.

Tests that the gate chain is properly wired into the entry flow
and correctly blocks/allows signals based on market conditions.
"""

import pytest
from unittest.mock import MagicMock
from app.domain.fabio_ai.services.gates.base import (
    GateContext,
    GateResult,
    EntryGate,
    GateChain,
)
from app.domain.fabio_ai.services.gates.cvd_gate import CVDGate
from app.domain.fabio_ai.services.gates.profile_shape_gate import ProfileShapeGate
from app.domain.fabio_ai.services.gates.momentum_fade_gate import MomentumFadeGate
from app.domain.fabio_ai.services.gates.contested_zone_gate import ContestedZoneGate


def _make_gate_context(
    cvd_slope=0.0,
    profile_shape="D",
    direction="LONG",
    session_data=None,
    footprint_candle=None,
) -> GateContext:
    """Create a GateContext for testing."""
    tick = MagicMock()
    tick.close = 100.0
    tick.open = 99.5
    tick.high = 100.5
    tick.low = 99.0
    tick.volume = 1000

    amt_result = MagicMock()
    amt_result.market_state = "BALANCED"
    amt_result.poc = 100.0
    amt_result.value_area_high = 101.0
    amt_result.value_area_low = 99.0
    amt_result.cvd_slope = cvd_slope
    amt_result.cvd_divergence = ""
    amt_result.aggression = 2.5
    amt_result.session_vwap = 100.0
    amt_result.profile_shape = profile_shape

    return GateContext(
        tick=tick,
        amt_result=amt_result,
        session_data=session_data or [],
        cvd_slope=cvd_slope,
        direction=direction,
        cvd_threshold=5000,
        footprint_candle=footprint_candle,
    )


class TestGateChainIntegration:
    """Test gate chain integration with entry flow."""

    def test_all_gates_pass_long(self):
        """All gates should pass for clean LONG setup."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
            MomentumFadeGate(),
            ContestedZoneGate(),
        ])

        ctx = _make_gate_context(
            cvd_slope=0.5,
            profile_shape="D",
            direction="LONG",
        )

        result = chain.evaluate(ctx)
        assert result.passed is True
        assert result.gate_name == "ALL"

    def test_cvd_gate_blocks_long(self):
        """CVD gate should block LONG when extreme selling."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
        ])

        ctx = _make_gate_context(
            cvd_slope=-6000,  # Extreme selling
            profile_shape="D",
            direction="LONG",
        )

        result = chain.evaluate(ctx)
        assert result.passed is False
        assert result.gate_name == "CVD"
        assert result.reason == "CVD_OPPOSING"

    def test_cvd_gate_blocks_short(self):
        """CVD gate should block SHORT when extreme buying."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
        ])

        ctx = _make_gate_context(
            cvd_slope=6000,  # Extreme buying
            profile_shape="D",
            direction="SHORT",
        )

        result = chain.evaluate(ctx)
        assert result.passed is False
        assert result.gate_name == "CVD"
        assert result.reason == "CVD_OPPOSING"

    def test_profile_shape_blocks_long_p_shape(self):
        """Profile shape gate should block LONG with P-shape."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
        ])

        ctx = _make_gate_context(
            cvd_slope=0.5,
            profile_shape="P",
            direction="LONG",
        )

        result = chain.evaluate(ctx)
        assert result.passed is False
        assert result.gate_name == "PROFILE_SHAPE"
        assert result.reason == "PROFILE_SHAPE_P"

    def test_profile_shape_blocks_short_b_shape(self):
        """Profile shape gate should block SHORT with b-shape."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
        ])

        ctx = _make_gate_context(
            cvd_slope=-0.5,
            profile_shape="b",
            direction="SHORT",
        )

        result = chain.evaluate(ctx)
        assert result.passed is False
        assert result.gate_name == "PROFILE_SHAPE"
        assert result.reason == "PROFILE_SHAPE_B"

    def test_gate_chain_order_matters(self):
        """Gates should be evaluated in order — first failure blocks."""
        chain = GateChain([
            CVDGate(),           # This should block first
            ProfileShapeGate(),  # This won't be reached
        ])

        ctx = _make_gate_context(
            cvd_slope=-6000,  # Blocks at CVD gate
            profile_shape="D",
            direction="LONG",
        )

        result = chain.evaluate(ctx)
        assert result.passed is False
        assert result.gate_name == "CVD"  # First gate blocked

    def test_empty_chain_passes(self):
        """Empty gate chain should pass."""
        chain = GateChain([])
        ctx = _make_gate_context()
        result = chain.evaluate(ctx)
        assert result.passed is True

    def test_single_gate_passes(self):
        """Single gate passing should return success."""
        chain = GateChain([CVDGate()])
        ctx = _make_gate_context(cvd_slope=0.5, direction="LONG")
        result = chain.evaluate(ctx)
        assert result.passed is True

    def test_gate_chain_with_all_concrete_gates(self):
        """Full gate chain with all concrete gates should work."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
            MomentumFadeGate(),
            ContestedZoneGate(),
        ])

        # Clean setup — all gates should pass
        ctx = _make_gate_context(
            cvd_slope=0.5,
            profile_shape="D",
            direction="LONG",
        )

        result = chain.evaluate(ctx)
        assert result.passed is True

    def test_gate_chain_blocks_on_multiple_conditions(self):
        """Multiple gates could block — first one wins."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
        ])

        # Both CVD and profile shape would block
        ctx = _make_gate_context(
            cvd_slope=-6000,  # CVD blocks
            profile_shape="P",  # Profile shape would also block
            direction="LONG",
        )

        result = chain.evaluate(ctx)
        assert result.passed is False
        # CVD should block first (it's first in chain)
        assert result.gate_name == "CVD"

    def test_gate_names_property(self):
        """gate_names should return all gate names."""
        chain = GateChain([
            CVDGate(),
            ProfileShapeGate(),
            MomentumFadeGate(),
            ContestedZoneGate(),
        ])
        assert chain.gate_names == ["CVD", "PROFILE_SHAPE", "MOMENTUM_FADE", "CONTESTED_ZONE"]

    def test_builder_pattern(self):
        """add() should support builder pattern."""
        chain = GateChain()
        chain.add(CVDGate()).add(ProfileShapeGate()).add(MomentumFadeGate())
        assert chain.gate_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])