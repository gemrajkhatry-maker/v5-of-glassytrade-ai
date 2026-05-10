"""Tests for exit_rules.py - Pure exit rule functions.

Covers:
- Exit classification (STOP_LOSS, TAKE_PROFIT, MANUAL)
- Time stop logic (session-aware, expiry, hard max)
- Risk-reward validation
- Spread blowout detection
"""

from __future__ import annotations

import pytest

from app.domain.exit.model.exit_models import ExitReason
from app.domain.exit.service.exit_rules import (
    TIME_STOP_TABLE,
    EXPIRY_TIME_STOP,
    HARD_MAX_HOLD_SECONDS,
    classify_exit,
    check_time_stop,
    is_valid_rr,
    check_spread_blowout,
)


# ============================================================
# classify_exit tests
# ============================================================

class TestClassifyExit:
    """Tests for exit classification logic."""

    def test_long_stop_loss_hit(self):
        assert classify_exit("LONG", 100.0, 95.0, 95.0, 110.0) == ExitReason.STOP_LOSS

    def test_long_stop_loss_below_sl(self):
        assert classify_exit("LONG", 100.0, 94.0, 95.0, 110.0) == ExitReason.STOP_LOSS

    def test_long_take_profit_hit(self):
        assert classify_exit("LONG", 100.0, 110.0, 95.0, 110.0) == ExitReason.TAKE_PROFIT

    def test_long_take_profit_above_tp(self):
        assert classify_exit("LONG", 100.0, 111.0, 95.0, 110.0) == ExitReason.TAKE_PROFIT

    def test_long_between_sl_and_tp_is_manual(self):
        assert classify_exit("LONG", 100.0, 105.0, 95.0, 110.0) == ExitReason.MANUAL

    def test_short_stop_loss_hit(self):
        assert classify_exit("SHORT", 100.0, 105.0, 105.0, 90.0) == ExitReason.STOP_LOSS

    def test_short_stop_loss_above_sl(self):
        assert classify_exit("SHORT", 100.0, 106.0, 105.0, 90.0) == ExitReason.STOP_LOSS

    def test_short_take_profit_hit(self):
        assert classify_exit("SHORT", 100.0, 90.0, 105.0, 90.0) == ExitReason.TAKE_PROFIT

    def test_short_take_profit_below_tp(self):
        assert classify_exit("SHORT", 100.0, 89.0, 105.0, 90.0) == ExitReason.TAKE_PROFIT

    def test_short_between_sl_and_tp_is_manual(self):
        assert classify_exit("SHORT", 100.0, 95.0, 105.0, 90.0) == ExitReason.MANUAL

    def test_manual_exit_overrides_everything(self):
        # Even if price hits SL, manual flag takes precedence
        assert classify_exit("LONG", 100.0, 95.0, 95.0, 110.0, is_manual=True) == ExitReason.MANUAL
        assert classify_exit("SHORT", 100.0, 105.0, 105.0, 90.0, is_manual=True) == ExitReason.MANUAL

    def test_long_at_exact_sl_is_stop_loss(self):
        assert classify_exit("LONG", 100.0, 95.0, 95.0, 110.0) == ExitReason.STOP_LOSS

    def test_short_at_exact_sl_is_stop_loss(self):
        assert classify_exit("SHORT", 100.0, 105.0, 105.0, 90.0) == ExitReason.STOP_LOSS


# ============================================================
# check_time_stop tests
# ============================================================

class TestCheckTimeStop:
    """Tests for session-aware time stop logic."""

    def test_morning_balanced_time_stop(self):
        limit = TIME_STOP_TABLE[("MORNING", "BALANCED")]
        assert not check_time_stop(limit - 1, "MORNING", "BALANCED")
        assert check_time_stop(limit, "MORNING", "BALANCED")
        assert check_time_stop(limit + 1, "MORNING", "BALANCED")

    def test_morning_imbalanced_time_stop(self):
        limit = TIME_STOP_TABLE[("MORNING", "IMBALANCED")]
        assert not check_time_stop(limit - 1, "MORNING", "IMBALANCED")
        assert check_time_stop(limit, "MORNING", "IMBALANCED")

    def test_afternoon_balanced_time_stop(self):
        limit = TIME_STOP_TABLE[("AFTERNOON", "BALANCED")]
        assert not check_time_stop(limit - 1, "AFTERNOON", "BALANCED")
        assert check_time_stop(limit, "AFTERNOON", "BALANCED")

    def test_afternoon_imbalanced_time_stop(self):
        limit = TIME_STOP_TABLE[("AFTERNOON", "IMBALANCED")]
        assert not check_time_stop(limit - 1, "AFTERNOON", "IMBALANCED")
        assert check_time_stop(limit, "AFTERNOON", "IMBALANCED")

    def test_unknown_phase_state_uses_default(self):
        # Default is 1800 seconds
        assert not check_time_stop(1799, "UNKNOWN", "UNKNOWN")
        assert check_time_stop(1800, "UNKNOWN", "UNKNOWN")

    def test_expiry_time_stop(self):
        assert not check_time_stop(EXPIRY_TIME_STOP - 1, is_expiry=True)
        assert check_time_stop(EXPIRY_TIME_STOP, is_expiry=True)
        assert check_time_stop(EXPIRY_TIME_STOP + 1, is_expiry=True)

    def test_expiry_ignores_session_phase(self):
        # When is_expiry=True, session_phase and market_state should be ignored
        assert check_time_stop(EXPIRY_TIME_STOP, "MORNING", "BALANCED", is_expiry=True)

    def test_hard_max_hold_seconds_defined(self):
        assert HARD_MAX_HOLD_SECONDS == 7200  # 2 hours

    def test_time_stop_table_values(self):
        """Verify time stop table has expected structure."""
        assert ("MORNING", "BALANCED") in TIME_STOP_TABLE
        assert ("MORNING", "IMBALANCED") in TIME_STOP_TABLE
        assert ("AFTERNOON", "BALANCED") in TIME_STOP_TABLE
        assert ("AFTERNOON", "IMBALANCED") in TIME_STOP_TABLE

    def test_imbalanced_allows_longer_hold(self):
        """Imbalanced market should allow longer holding time."""
        morning_balanced = TIME_STOP_TABLE[("MORNING", "BALANCED")]
        morning_imbalanced = TIME_STOP_TABLE[("MORNING", "IMBALANCED")]
        assert morning_imbalanced > morning_balanced

        afternoon_balanced = TIME_STOP_TABLE[("AFTERNOON", "BALANCED")]
        afternoon_imbalanced = TIME_STOP_TABLE[("AFTERNOON", "IMBALANCED")]
        assert afternoon_imbalanced > afternoon_balanced

    def test_morning_allows_longer_than_afternoon(self):
        """Morning session should allow longer holding than afternoon."""
        morning_balanced = TIME_STOP_TABLE[("MORNING", "BALANCED")]
        afternoon_balanced = TIME_STOP_TABLE[("AFTERNOON", "BALANCED")]
        assert morning_balanced > afternoon_balanced

    def test_zero_hold_time_never_triggers(self):
        assert not check_time_stop(0, "MORNING", "BALANCED")
        assert not check_time_stop(0, is_expiry=True)


# ============================================================
# is_valid_rr tests
# ============================================================

class TestIsValidRR:
    """Tests for risk-reward validation."""

    def test_valid_long_rr(self):
        # Entry 100, SL 95 (risk 5), TP 110 (reward 10) -> RR = 2.0
        assert is_valid_rr(100.0, 95.0, 110.0, "LONG")

    def test_valid_short_rr(self):
        # Entry 100, SL 105 (risk 5), TP 90 (reward 10) -> RR = 2.0
        assert is_valid_rr(100.0, 105.0, 90.0, "SHORT")

    def test_invalid_long_rr_below_minimum(self):
        # Entry 100, SL 95 (risk 5), TP 102 (reward 2) -> RR = 0.4
        assert not is_valid_rr(100.0, 95.0, 102.0, "LONG")

    def test_invalid_short_rr_below_minimum(self):
        # Entry 100, SL 105 (risk 5), TP 98 (reward 2) -> RR = 0.4
        assert not is_valid_rr(100.0, 105.0, 98.0, "SHORT")

    def test_rr_exactly_at_minimum(self):
        # Entry 100, SL 95 (risk 5), TP 107.5 (reward 7.5) -> RR = 1.5
        assert is_valid_rr(100.0, 95.0, 107.5, "LONG", min_rr=1.5)

    def test_rr_just_below_minimum(self):
        assert not is_valid_rr(100.0, 95.0, 107.4, "LONG", min_rr=1.5)

    def test_zero_risk_is_invalid(self):
        # Entry == SL means zero risk
        assert not is_valid_rr(100.0, 100.0, 110.0, "LONG")
        assert not is_valid_rr(100.0, 100.0, 90.0, "SHORT")

    def test_custom_min_rr(self):
        # RR = 2.0
        assert is_valid_rr(100.0, 95.0, 110.0, "LONG", min_rr=2.0)
        assert not is_valid_rr(100.0, 95.0, 110.0, "LONG", min_rr=2.1)

    def test_long_reward_calculation(self):
        """For LONG: reward = tp - entry"""
        assert is_valid_rr(100.0, 90.0, 120.0, "LONG", min_rr=2.0)
        # risk = 10, reward = 20, RR = 2.0

    def test_short_reward_calculation(self):
        """For SHORT: reward = entry - tp"""
        assert is_valid_rr(100.0, 110.0, 80.0, "SHORT", min_rr=2.0)
        # risk = 10, reward = 20, RR = 2.0


# ============================================================
# check_spread_blowout tests
# ============================================================

class TestCheckSpreadBlowout:
    """Tests for spread blowout detection."""

    def test_normal_spread_not_blowout(self):
        assert not check_spread_blowout(0.005)

    def test_threshold_exactly_not_blowout(self):
        # spread_pct > threshold, so equal is not blowout
        assert not check_spread_blowout(0.01)

    def test_above_threshold_is_blowout(self):
        assert check_spread_blowout(0.031)  # 3.1% > 3% threshold

    def test_zero_spread_not_blowout(self):
        assert not check_spread_blowout(0.0)

    def test_custom_threshold(self):
        assert not check_spread_blowout(0.04, threshold=0.05)
        assert check_spread_blowout(0.06, threshold=0.05)

    def test_very_large_spread_is_blowout(self):
        assert check_spread_blowout(0.10)  # 10% spread
