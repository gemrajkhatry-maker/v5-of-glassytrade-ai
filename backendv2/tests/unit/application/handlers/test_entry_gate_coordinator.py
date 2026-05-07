"""Tests for entry_gate_coordinator.py — gate coordination."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.entry_gate_coordinator import EntryGateCoordinator


class MockTick:
    def __init__(self, close=100.0, symbol="NIFTY"):
        self.close = close
        self.symbol = symbol


class MockAmtResult:
    def __init__(self, **kwargs):
        self.market_state = kwargs.get("market_state", "BALANCED")
        self.aggression_score = kwargs.get("aggression_score", 3.0)
        self.aggression = kwargs.get("aggression", 3.0)
        self.drive_number = kwargs.get("drive_number", 0)
        self.drive_entry_valid = kwargs.get("drive_entry_valid", False)
        self.cvd_slope = kwargs.get("cvd_slope", 0.0)
        self.profile_shape = kwargs.get("profile_shape", "")
        self.session_vwap = kwargs.get("session_vwap", 99.0)
        self.is_extreme_deviation = kwargs.get("is_extreme_deviation", False)
        self.poc = kwargs.get("poc", 100.0)


class MockOHLC:
    def __init__(self, close=100.0, time="2024-01-01T09:15:00"):
        self.close = close
        self.time = time


class TestCheckEntryEligibility:
    """Tests for check_entry_eligibility()."""

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_all_gates_pass(self, mock_gates):
        """When all gates pass, returns (True, 'All gates passed', drive_valid)."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0)] * 50
        amt = MockAmtResult(drive_entry_valid=True)
        tick = MockTick(close=100.0)
        passed, reason, drive_valid = coordinator.check_entry_eligibility(
            data, amt, tick, tick_size=0.05
        )
        assert passed is True
        assert "All gates passed" in reason
        assert drive_valid is True

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_gate_pipeline_fails(self, mock_gates):
        """When gate pipeline fails, returns failure reason."""
        mock_gates.return_value = (False, "STALE_TICK", "Tick too old", 0, 0)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC()] * 50
        amt = MockAmtResult()
        tick = MockTick()
        passed, reason, drive_valid = coordinator.check_entry_eligibility(
            data, amt, tick, tick_size=0.05
        )
        assert passed is False
        assert "Gate pipeline" in reason
        assert "STALE_TICK" in reason
        assert drive_valid is False

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_cvd_hard_gate_blocks_extreme_selling(self, mock_gates):
        """CVD extreme selling in BALANCED blocks entry."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC()] * 50
        amt = MockAmtResult(market_state="BALANCED", cvd_slope=-150.0)
        tick = MockTick()
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="LONG", tick_size=0.05
        )
        assert passed is False
        assert "CVD extreme selling" in reason

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_cvd_hard_gate_blocks_extreme_buying(self, mock_gates):
        """CVD extreme buying in BALANCED blocks entry."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC()] * 50
        amt = MockAmtResult(market_state="BALANCED", cvd_slope=150.0)
        tick = MockTick()
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="SHORT", tick_size=0.05
        )
        assert passed is False
        assert "CVD extreme buying" in reason

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_profile_shape_p_blocks_long(self, mock_gates):
        """P-shape blocks LONG entry."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC()] * 50
        amt = MockAmtResult(profile_shape="P")
        tick = MockTick()
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="LONG", tick_size=0.05
        )
        assert passed is False
        assert "P-shape blocks LONG" in reason

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_profile_shape_b_blocks_short(self, mock_gates):
        """b-shape blocks SHORT entry."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC()] * 50
        amt = MockAmtResult(profile_shape="b")
        tick = MockTick()
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="SHORT", tick_size=0.05
        )
        assert passed is False
        assert "b-shape blocks SHORT" in reason

    @patch("app.application.handlers.entry_gate_coordinator.run_entry_gates")
    def test_vwap_bias_logged_not_blocking(self, mock_gates):
        """VWAP bias is logged as debug but does not block entry."""
        mock_gates.return_value = (True, "TRADE", "", 3, 4)
        coordinator = EntryGateCoordinator()
        data = [MockOHLC()] * 50
        amt = MockAmtResult(session_vwap=101.0)
        tick = MockTick(close=100.0)  # Below VWAP for LONG
        passed, reason, _ = coordinator.check_entry_eligibility(
            data, amt, tick, direction="LONG", tick_size=0.05
        )
        assert passed is True  # VWAP bias doesn't block


class TestCheckCvdHardGate:
    """Tests for _check_cvd_hard_gate()."""

    def test_extreme_selling_in_balanced_blocks(self):
        """Extreme selling CVD in BALANCED blocks entry."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(market_state="BALANCED", cvd_slope=-150.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "LONG")
        assert passed is False
        assert "extreme selling" in reason

    def test_extreme_buying_in_balanced_blocks(self):
        """Extreme buying CVD in BALANCED blocks entry."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(market_state="BALANCED", cvd_slope=150.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "SHORT")
        assert passed is False
        assert "extreme buying" in reason

    def test_cvd_opposing_long_blocks(self):
        """Strong negative CVD blocks LONG."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(cvd_slope=-60.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "LONG")
        assert passed is False
        assert "opposing LONG" in reason

    def test_cvd_opposing_short_blocks(self):
        """Strong positive CVD blocks SHORT."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(cvd_slope=60.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "SHORT")
        assert passed is False
        assert "opposing SHORT" in reason

    def test_cvd_aligned_long_passes(self):
        """Positive CVD allows LONG."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(cvd_slope=30.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "LONG")
        assert passed is True

    def test_cvd_aligned_short_passes(self):
        """Negative CVD allows SHORT."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(cvd_slope=-30.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "SHORT")
        assert passed is True

    def test_imbalanced_market_passes(self):
        """IMBALANCED market passes when CVD is moderate (not opposing)."""
        coordinator = EntryGateCoordinator()
        # Use moderate negative CVD that doesn't exceed hard block threshold
        amt = MockAmtResult(market_state="IMBALANCED", cvd_slope=-30.0)
        passed, reason = coordinator._check_cvd_hard_gate(amt, "LONG")
        assert passed is True

    def test_zero_cvd_passes(self):
        """Zero CVD slope passes for any direction."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(cvd_slope=0.0)
        assert coordinator._check_cvd_hard_gate(amt, "LONG")[0] is True
        assert coordinator._check_cvd_hard_gate(amt, "SHORT")[0] is True


class TestCheckProfileShapeGate:
    """Tests for _check_profile_shape_gate()."""

    def test_p_shape_blocks_long(self):
        """P-shape blocks LONG entry."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(profile_shape="P")
        passed, reason = coordinator._check_profile_shape_gate(amt, "LONG")
        assert passed is False
        assert "P-shape blocks LONG" in reason

    def test_b_shape_blocks_short(self):
        """b-shape blocks SHORT entry."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(profile_shape="b")
        passed, reason = coordinator._check_profile_shape_gate(amt, "SHORT")
        assert passed is False
        assert "b-shape blocks SHORT" in reason

    def test_b_shape_long_passes(self):
        """b-shape is fine for LONG."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(profile_shape="b")
        passed, _ = coordinator._check_profile_shape_gate(amt, "LONG")
        assert passed is True

    def test_p_shape_short_passes(self):
        """P-shape is fine for SHORT."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(profile_shape="P")
        passed, _ = coordinator._check_profile_shape_gate(amt, "SHORT")
        assert passed is True

    def test_neutral_shape_passes(self):
        """D or B shape passes for any direction."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(profile_shape="D")
        assert coordinator._check_profile_shape_gate(amt, "LONG")[0] is True
        assert coordinator._check_profile_shape_gate(amt, "SHORT")[0] is True

    def test_no_profile_data_passes(self):
        """Empty profile_shape passes."""
        coordinator = EntryGateCoordinator()
        amt = MockAmtResult(profile_shape="")
        passed, reason = coordinator._check_profile_shape_gate(amt, "LONG")
        assert passed is True
        assert "No profile shape" in reason


class TestCheckVwapBias:
    """Tests for check_vwap_bias()."""

    def test_long_below_vwap_warning(self):
        """LONG below VWAP produces warning."""
        coordinator = EntryGateCoordinator()
        result = coordinator.check_vwap_bias("LONG", 99.0, 100.0, 105.0, 95.0)
        assert result["warning"] is True
        assert result["overextended"] is False

    def test_long_above_vwap_upper_2_overextended(self):
        """LONG above VWAP+2sigma is overextended."""
        coordinator = EntryGateCoordinator()
        result = coordinator.check_vwap_bias("LONG", 106.0, 100.0, 105.0, 95.0)
        assert result["warning"] is False
        assert result["overextended"] is True

    def test_short_above_vwap_warning(self):
        """SHORT above VWAP produces warning."""
        coordinator = EntryGateCoordinator()
        result = coordinator.check_vwap_bias("SHORT", 101.0, 100.0, 105.0, 95.0)
        assert result["warning"] is True

    def test_short_below_vwap_lower_2_overextended(self):
        """SHORT below VWAP-2sigma is overextended."""
        coordinator = EntryGateCoordinator()
        result = coordinator.check_vwap_bias("SHORT", 94.0, 100.0, 105.0, 95.0)
        assert result["warning"] is False
        assert result["overextended"] is True

    def test_neutral_position_no_warning(self):
        """LONG above VWAP has no warning."""
        coordinator = EntryGateCoordinator()
        result = coordinator.check_vwap_bias("LONG", 102.0, 100.0, 105.0, 95.0)
        assert result["warning"] is False
        assert result["overextended"] is False

    def test_zero_vwap_no_warning(self):
        """When VWAP is 0, no checks performed."""
        coordinator = EntryGateCoordinator()
        result = coordinator.check_vwap_bias("LONG", 99.0, 0.0, 0.0, 0.0)
        assert result["warning"] is False
        assert result["overextended"] is False


class TestCheckConfirmationBundle:
    """Tests for check_confirmation_bundle()."""

    def test_price_changed_returns_true(self):
        """When current close != previous close, returns True."""
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0), MockOHLC(close=100.5)]
        tick = MockOHLC(close=101.0)
        assert coordinator.check_confirmation_bundle(data, tick) is True

    def test_same_close_returns_false(self):
        """When current close == previous close, returns False."""
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0), MockOHLC(close=100.0)]
        tick = MockOHLC(close=100.0)
        assert coordinator.check_confirmation_bundle(data, tick) is False

    def test_insufficient_data_returns_false(self):
        """When less than 2 candles, returns False."""
        coordinator = EntryGateCoordinator()
        data = [MockOHLC(close=100.0)]
        tick = MockOHLC(close=101.0)
        assert coordinator.check_confirmation_bundle(data, tick) is False
