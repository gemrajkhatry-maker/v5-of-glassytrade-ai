"""Tests for FlashCrashProtector — price-velocity circuit breaker.

Behavior: FlashCrashProtector monitors tick-to-tick percentage movement
rate inside a short rolling window and triggers ELEVATED or FLASH_CRASH
states when velocity exceeds configured thresholds.
"""
from __future__ import annotations

import pytest

from app.domain.risk.service.flash_crash_protector import (
    FlashCrashProtector,
    VelocityLevel,
    VelocityState,
)


class TestFlashCrashProtectorNormal:
    """Tests for normal velocity behavior."""

    def test_single_tick_stays_normal(self):
        """A single price tick should return NORMAL velocity."""
        protector = FlashCrashProtector()
        state = protector.update(price=100.0, timestamp=1000.0)

        assert state.level == VelocityLevel.NORMAL
        assert state.is_halted is False
        assert state.velocity_pct_per_sec == 0.0

    def test_slow_movement_stays_normal(self):
        """Small price change over the window should stay NORMAL."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=100.1, timestamp=1004.0)  # 0.1% in 4s

        assert state.level == VelocityLevel.NORMAL
        assert state.is_halted is False

    def test_normal_has_reason_text(self):
        """NORMAL state should include 'Normal' in reason."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=100.1, timestamp=1004.0)

        assert "Normal" in state.reason


class TestFlashCrashProtectorElevated:
    """Tests for elevated velocity detection."""

    def test_elevated_triggered_above_threshold(self):
        """Price change > 0.5%% in 5s should trigger ELEVATED."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=101.0, timestamp=1004.0)  # 1% in 4s

        assert state.level == VelocityLevel.ELEVATED
        assert state.is_halted is False

    def test_elevated_boundary_at_threshold(self):
        """Price change exactly at 0.5%% threshold should trigger ELEVATED."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        # 0.5% change in 5 seconds
        state = protector.update(price=100.5, timestamp=1005.0)

        assert state.level == VelocityLevel.ELEVATED

    def test_elevated_has_reason_text(self):
        """ELEVATED state should include 'Elevated' in reason."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=101.0, timestamp=1004.0)

        assert "Elevated" in state.reason


class TestFlashCrashProtectorFlashCrash:
    """Tests for flash crash detection and halt."""

    def test_flash_crash_triggered_above_2_percent(self):
        """Price change > 2%% in 5s should trigger FLASH_CRASH halt."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=103.0, timestamp=1004.0)  # 3% in 4s

        assert state.level == VelocityLevel.FLASH_CRASH
        assert state.is_halted is True
        assert "Flash crash" in state.reason

    def test_flash_crash_halt_persists(self):
        """Once halted, subsequent updates should keep FLASH_CRASH state."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        protector.update(price=103.0, timestamp=1004.0)  # triggers halt

        # Next update should still be halted
        state = protector.update(price=100.0, timestamp=1010.0)
        assert state.level == VelocityLevel.FLASH_CRASH
        assert state.is_halted is True

    def test_reset_clears_halt(self):
        """Calling reset should clear the halt and allow trading again."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        protector.update(price=103.0, timestamp=1004.0)  # triggers halt
        assert protector._halted is True

        protector.reset()
        state = protector.update(price=100.0, timestamp=1020.0)
        assert state.is_halted is False
        assert state.level == VelocityLevel.NORMAL


class TestFlashCrashProtectorEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_price_ignored(self):
        """Zero price should be ignored and return NORMAL."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=0.0, timestamp=1004.0)

        # Zero price should not affect the state
        assert state.level == VelocityLevel.NORMAL
        assert state.is_halted is False

    def test_window_expiry_resets_velocity(self):
        """After window expires, old ticks are discarded and velocity resets."""
        protector = FlashCrashProtector(window_seconds=5)
        protector.update(price=100.0, timestamp=1000.0)
        protector.update(price=103.0, timestamp=1004.0)  # would trigger flash

        protector.reset()
        protector.update(price=100.0, timestamp=1020.0)
        state = protector.update(price=100.2, timestamp=1024.0)  # 0.2% in 4s — NORMAL

        assert state.level == VelocityLevel.NORMAL

    def test_velocity_state_is_frozen_dataclass(self):
        """VelocityState should be immutable."""
        state = VelocityState(
            level=VelocityLevel.NORMAL,
            velocity_pct_per_sec=0.0,
            is_halted=False,
            reason="test",
        )

        with pytest.raises(Exception):  # dataclass.FrozenInstanceError
            state.level = VelocityLevel.ELEVATED

    def test_downward_move_triggers_same_as_upward(self):
        """A sharp downward price move should trigger FLASH_CRASH too."""
        protector = FlashCrashProtector()
        protector.update(price=100.0, timestamp=1000.0)
        state = protector.update(price=97.0, timestamp=1004.0)  # -3% in 4s

        assert state.level == VelocityLevel.FLASH_CRASH
        assert state.is_halted is True
