"""Tests for Triple-A Framework — Absorption → Accumulation → Aggressive Breakout."""

import pytest

from app.domain.services.aaa_precondition_engine import (
    AAAPreconditionEngine,
    Precondition,
)


class _FakePhaseState:
    def __init__(self, allowed_action="ALL_MODELS", phase="AAA_WINDOW"):
        self.allowed_action = allowed_action
        self._phase_str = phase

    @property
    def phase(self):
        # Return an object with .value attribute
        class _PhaseEnum:
            def __init__(self, v):
                self.value = v

        return _PhaseEnum(self._phase_str)


class _FakeTick:
    def __init__(self, high=100, low=95, close=98, volume=5000):
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class TestAAAPreconditionEngine:
    """Test AAA precondition engine (5 preconditions)."""

    def _make_engine(self):
        return AAAPreconditionEngine(
            buffer_pct=0.005,
            volume_spike_multiplier=2.0,
            candle_body_threshold=0.40,
        )

    def _make_tick(self, high=100, low=95, close=98, volume=10000):
        return _FakeTick(high=high, low=low, close=close, volume=volume)

    def test_all_pass_imbalanced(self):
        """All 5 preconditions pass for IMBALANCED state."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=94.4,  # within 0.5% of VAL=94.0
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(
                high=96, low=93, close=95, volume=10000
            ),  # bullish candle
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert result.all_passed, f"Failed: {result.failed} — {result.reason}"
        assert len(result.passed) == 5

    def test_pre1_state_blocks_balanced(self):
        """PRE-1: BALANCED state blocks AAA (needs IMBALANCED/IMBALANCED)."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="BALANCED",
            leg_state="BALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=100.0,
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(),
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE1_STATE in result.failed

    def test_pre2_time_blocks_midday(self):
        """PRE-2: MIDDAY phase blocks AAA (needs ALL_MODELS or AAA_ONLY)."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("MR_ONLY", "MIDDAY"),
            profile_shape="P",
            price=94.4,
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(),
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE2_TIME in result.failed

    def test_pre3_shape_blocks_wrong_shape(self):
        """PRE-3: Wrong profile shape blocks LONG (needs P-shape)."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="b",  # b-shape is for SHORT, not LONG
            price=94.4,
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(),
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE3_SHAPE in result.failed

    def test_pre4_price_far_from_val(self):
        """PRE-4: Price far from VAL blocks LONG entry."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=100.0,  # far from VAL=94
            val=94.0,
            vah=105.0,
            poc=150.0,  # far from price to avoid POC proximity check passing PRE-4
            current_candle=self._make_tick(),
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE4_PRICE in result.failed

    def test_pre5_absorption_no_volume_spike(self):
        """PRE-5: No volume spike blocks absorption confirmation."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=94.4,  # near VAL
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(
                high=96, low=93, close=95, volume=5000
            ),  # below 2.0x avg
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE5_ABSORPTION in result.failed

    def test_pre5_absorption_wrong_delta(self):
        """PRE-5: Wrong delta direction blocks absorption for LONG."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=94.4,
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(high=96, low=93, close=95, volume=10000),
            avg_volume=4000,
            delta=-100,  # negative delta for LONG
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE5_ABSORPTION in result.failed

    def test_pre5_absorption_wrong_ofi(self):
        """PRE-5: Wrong OFI direction blocks absorption for LONG."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=94.4,
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(high=96, low=93, close=95, volume=10000),
            avg_volume=4000,
            delta=100,
            ofi=-0.2,  # negative OFI for LONG
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE5_ABSORPTION in result.failed

    def test_short_all_pass(self):
        """All preconditions pass for SHORT in IMBALANCED state."""
        engine = self._make_engine()
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="b",  # b-shape for SHORT
            price=104.5,  # near VAH=105
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(
                high=106, low=103, close=104, volume=10000
            ),  # bearish candle
            avg_volume=4000,
            delta=-100,
            ofi=-0.2,
            direction="SHORT",
        )
        assert result.all_passed, f"Failed: {result.failed} — {result.reason}"

    def test_volume_spike_2x_required(self):
        """Volume spike must be >= 2.0x average (not 1.5x)."""
        engine = self._make_engine()
        # 1.9x volume should fail on PRE-5
        result = engine.evaluate(
            session_state="IMBALANCED",
            leg_state="IMBALANCED",
            phase_state=_FakePhaseState("ALL_MODELS", "AAA_WINDOW"),
            profile_shape="P",
            price=94.4,
            val=94.0,
            vah=105.0,
            poc=100.0,
            current_candle=self._make_tick(
                high=96, low=93, close=95, volume=7600
            ),  # 1.9x avg
            avg_volume=4000,
            delta=100,
            ofi=0.2,
            direction="LONG",
        )
        assert not result.all_passed
        assert Precondition.PRE5_ABSORPTION in result.failed
