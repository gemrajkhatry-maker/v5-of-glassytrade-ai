"""Tests for LossTracker — daily loss counting, circuit breakers, cushion sizing."""

import pytest

from quant.execution.loss_tracker import LossTracker


class TestDailyLossCounting:
    def setup_method(self):
        self.tracker = LossTracker(max_daily_losses=3)

    def test_initial_state_allows_trading(self):
        assert not self.tracker.is_daily_limit_reached("NIFTY")

    def test_symbol_limit_reached_at_max_daily_losses(self):
        self.tracker.record_loss("NIFTY")
        self.tracker.record_loss("NIFTY")
        self.tracker.record_loss("NIFTY")
        assert self.tracker.is_daily_limit_reached("NIFTY")
        assert not self.tracker.is_daily_limit_reached("BANKNIFTY")

    def test_global_limit_is_max_times_three(self):
        for _ in range(8):
            self.tracker.record_loss("NIFTY")
        assert self.tracker.is_daily_limit_reached("NIFTY")

    def test_win_resets_consecutive_losses(self):
        self.tracker.record_loss("NIFTY", stop_price=100.0)
        self.tracker.record_loss("NIFTY", stop_price=100.0)
        self.tracker.record_win("NIFTY")
        assert not self.tracker.should_block_entry("NIFTY", current_price=101.0, current_atr=1.0)

    def test_block_within_atr_buffer(self):
        self.tracker.record_loss("NIFTY", stop_price=100.0)
        self.tracker.record_loss("NIFTY", stop_price=99.0)
        assert self.tracker.should_block_entry("NIFTY", current_price=99.5, current_atr=1.0)

    def test_allows_beyond_atr_buffer(self):
        self.tracker.record_loss("NIFTY", stop_price=100.0)
        self.tracker.record_loss("NIFTY", stop_price=99.0)
        assert not self.tracker.should_block_entry("NIFTY", current_price=97.0, current_atr=1.0)

    def test_reset_consecutive_losses(self):
        self.tracker.record_loss("NIFTY", stop_price=100.0)
        self.tracker.reset_consecutive_losses("NIFTY")
        assert not self.tracker.should_block_entry("NIFTY", current_price=100.5, current_atr=1.0)


class TestComputeDynamicRisk:
    def test_conservative_when_negative(self):
        tracker = LossTracker()
        risk_pct, mode = tracker.compute_dynamic_risk(100_000.0, session_realized_pnl=-1000.0)
        assert risk_pct == 0.0025
        assert mode == "Conservative"

    def test_scales_with_profit(self):
        tracker = LossTracker()
        risk_pct, mode = tracker.compute_dynamic_risk(100_000.0, session_realized_pnl=5000.0)
        assert risk_pct > 0.0025

    def test_caps_below_five_tenths_percent(self):
        tracker = LossTracker()
        risk_pct, _ = tracker.compute_dynamic_risk(100_000.0, session_realized_pnl=500_000.0)
        assert risk_pct <= 0.0050


class TestSessionPnl:
    def test_circuit_and_target(self):
        tracker = LossTracker()
        tracker.add_realized_pnl(-35_000.0)
        assert tracker.is_session_circuit_hit()
        assert tracker.get_session_status() == "CIRCUIT_HIT"

    def test_target_hit(self):
        tracker = LossTracker()
        tracker.add_realized_pnl(20_000.0)
        assert tracker.is_session_target_hit()
        assert tracker.get_session_status() == "TARGET_HIT"
