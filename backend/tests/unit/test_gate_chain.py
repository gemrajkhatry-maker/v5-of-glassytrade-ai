"""Unit tests for GateChain pattern.

Tests the extensible entry gate evaluation system.
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


class MockGate(EntryGate):
    """Mock gate for testing."""

    def __init__(self, name: str, should_pass: bool = True):
        self._name = name
        self._should_pass = should_pass

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, context: GateContext) -> GateResult:
        if self._should_pass:
            return GateResult(
                passed=True,
                gate_name=self._name,
                reason="OK",
                detail=f"{self._name} passed",
            )
        return GateResult(
            passed=False,
            gate_name=self._name,
            reason="BLOCKED",
            detail=f"{self._name} blocked",
            confidence_adjustment=-0.5,
        )


class TestGateChain:
    """Test suite for GateChain."""

    def test_all_gates_pass(self):
        """All gates passing should return success."""
        chain = GateChain([
            MockGate("Gate1", should_pass=True),
            MockGate("Gate2", should_pass=True),
            MockGate("Gate3", should_pass=True),
        ])

        context = MagicMock()
        result = chain.evaluate(context)

        assert result.passed is True
        assert result.gate_name == "ALL"
        assert "3 gates passed" in result.detail

    def test_first_gate_blocks(self):
        """First gate failing should return immediately."""
        chain = GateChain([
            MockGate("Gate1", should_pass=False),
            MockGate("Gate2", should_pass=True),
            MockGate("Gate3", should_pass=True),
        ])

        context = MagicMock()
        result = chain.evaluate(context)

        assert result.passed is False
        assert result.gate_name == "Gate1"
        assert result.reason == "BLOCKED"

    def test_middle_gate_blocks(self):
        """Middle gate failing should return its result."""
        chain = GateChain([
            MockGate("Gate1", should_pass=True),
            MockGate("Gate2", should_pass=False),
            MockGate("Gate3", should_pass=True),
        ])

        context = MagicMock()
        result = chain.evaluate(context)

        assert result.passed is False
        assert result.gate_name == "Gate2"

    def test_empty_chain_passes(self):
        """Empty chain should pass."""
        chain = GateChain([])
        context = MagicMock()
        result = chain.evaluate(context)
        assert result.passed is True

    def test_add_builder_pattern(self):
        """add() should support builder pattern."""
        chain = GateChain()
        chain.add(MockGate("Gate1")).add(MockGate("Gate2"))
        assert chain.gate_count == 2

    def test_gate_names(self):
        """gate_names should return all gate names."""
        chain = GateChain([
            MockGate("CVD"),
            MockGate("ProfileShape"),
            MockGate("MomentumFade"),
        ])
        assert chain.gate_names == ["CVD", "ProfileShape", "MomentumFade"]


class TestCVDGate:
    """Test suite for CVDGate."""

    def _make_context(self, cvd_slope: float, direction: str) -> GateContext:
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = cvd_slope
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = "D"

        return GateContext(
            tick=tick,
            amt_result=amt_result,
            session_data=[],
            cvd_slope=cvd_slope,
            direction=direction,
            cvd_threshold=5000,
        )

    def test_long_blocked_by_extreme_selling(self):
        """LONG should be blocked when CVD slope < -5000."""
        gate = CVDGate()
        context = self._make_context(cvd_slope=-6000, direction="LONG")
        result = gate.evaluate(context)
        assert result.passed is False
        assert result.reason == "CVD_OPPOSING"

    def test_short_blocked_by_extreme_buying(self):
        """SHORT should be blocked when CVD slope > 5000."""
        gate = CVDGate()
        context = self._make_context(cvd_slope=6000, direction="SHORT")
        result = gate.evaluate(context)
        assert result.passed is False
        assert result.reason == "CVD_OPPOSING"

    def test_long_passes_with_normal_cvd(self):
        """LONG should pass with normal CVD slope."""
        gate = CVDGate()
        context = self._make_context(cvd_slope=100, direction="LONG")
        result = gate.evaluate(context)
        assert result.passed is True

    def test_short_passes_with_normal_cvd(self):
        """SHORT should pass with normal CVD slope."""
        gate = CVDGate()
        context = self._make_context(cvd_slope=-100, direction="SHORT")
        result = gate.evaluate(context)
        assert result.passed is True


class TestProfileShapeGate:
    """Test suite for ProfileShapeGate."""

    def _make_context(self, profile_shape: str, direction: str) -> GateContext:
        tick = MagicMock()
        tick.close = 100.0
        tick.volume = 1000
        tick.delta = 50

        amt_result = MagicMock()
        amt_result.market_state = "BALANCED"
        amt_result.poc = 100.0
        amt_result.value_area_high = 101.0
        amt_result.value_area_low = 99.0
        amt_result.cvd_slope = 0.5
        amt_result.aggression = 2.5
        amt_result.session_vwap = 100.0
        amt_result.profile_shape = profile_shape

        return GateContext(
            tick=tick,
            amt_result=amt_result,
            session_data=[],
            direction=direction,
        )

    def test_long_blocked_by_p_shape(self):
        """LONG should be blocked when profile is P-shape."""
        gate = ProfileShapeGate()
        context = self._make_context("P", "LONG")
        result = gate.evaluate(context)
        assert result.passed is False
        assert result.reason == "PROFILE_SHAPE_P"

    def test_short_blocked_by_b_shape(self):
        """SHORT should be blocked when profile is b-shape."""
        gate = ProfileShapeGate()
        context = self._make_context("b", "SHORT")
        result = gate.evaluate(context)
        assert result.passed is False
        assert result.reason == "PROFILE_SHAPE_B"

    def test_long_passes_with_d_shape(self):
        """LONG should pass with D-shape."""
        gate = ProfileShapeGate()
        context = self._make_context("D", "LONG")
        result = gate.evaluate(context)
        assert result.passed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])