"""
Spec Compliance Tests - Verify all thresholds match plan specification.

These tests ensure that the implementation matches the documented requirements
and that no threshold drift has occurred.
"""

import pytest
from src.config.engine_config import CFG


class TestSpecCompliance:
    """Verify all thresholds match plan specification (FR requirements)."""

    # =========================================================================
    # VOLUME PROFILE THRESHOLDS (FR-02)
    # =========================================================================

    def test_lvn_threshold(self):
        """SC-01: LVN threshold = 0.15 (15% of mean)."""
        assert CFG.lvn_threshold_pct == 0.15, "LVN threshold must be 0.15 per FR-02-08"

    def test_hvn_threshold(self):
        """SC-02: HVN threshold = 2.00 (200% of mean)."""
        assert CFG.hvn_threshold_pct == 2.00, "HVN threshold must be 2.00 per FR-02-09"

    def test_value_area_pct(self):
        """SC-03: Value area = 70% of volume."""
        assert CFG.value_area_pct == 0.70, "Value area must be 70% per FR-02-03"

    # =========================================================================
    # ORDER FLOW THRESHOLDS (FR-03)
    # =========================================================================

    def test_footprint_imbalance_ratio(self):
        """SC-04: Footprint imbalance ratio = 3.0 (300%)."""
        assert CFG.footprint_imbalance_ratio == 3.0, "Imbalance ratio must be 3.0 per FR-03-06"

    def test_footprint_imbalance_pct(self):
        """Footprint imbalance confirmation = 40% of cells."""
        assert CFG.footprint_imbalance_pct == 0.40, "Imbalance pct must be 0.40 per FR-03-06"

    def test_cvd_slope_window(self):
        """SC-06: CVD slope window = 20 candles."""
        assert CFG.cvd_slope_window == 20, "CVD slope window must be 20 per FR-03-02"

    def test_absorption_range_atr(self):
        """SC-12: Absorption range = ATR × 0.30."""
        assert CFG.absorption_range_atr == 0.30, "Absorption range must be 0.30 per FR-03-09"

    def test_absorption_vol_mult(self):
        """SC-13: Absorption volume multiplier = 2.0."""
        assert CFG.absorption_vol_mult == 2.0, "Absorption vol mult must be 2.0 per FR-03-09"

    def test_big_trade_multiplier(self):
        """SC-14: Big trade multiplier = 5.0."""
        assert CFG.big_trade_multiplier == 5.0, "Big trade multiplier must be 5.0 per FR-03-11"

    def test_ofi_window(self):
        """OFI calculation window = 10 candles."""
        assert CFG.ofi_window == 10, "OFI window must be 10 per FR-03-12"

    # =========================================================================
    # AGGRESSION THRESHOLDS (FR-06)
    # =========================================================================

    def test_min_aggression_score(self):
        """SC-05: Minimum aggression score = 2.0."""
        assert CFG.min_aggression_score == 2.0, "Min aggression must be 2.0 per FR-06-08"

    def test_pyramid_aggression_score(self):
        """Pyramid aggression threshold = 3.0."""
        assert CFG.pyramid_aggression_score == 3.0, "Pyramid aggression must be 3.0 per FR-06-09"

    # =========================================================================
    # RISK MANAGEMENT THRESHOLDS (FR-10)
    # =========================================================================

    def test_risk_per_trade_pct(self):
        """Risk per trade = 0.5% of equity."""
        assert CFG.risk_per_trade_pct == 0.005, "Risk per trade must be 0.005 per FR-10-01"

    def test_max_daily_loss_pct(self):
        """SC-07: Max daily loss = 2% of equity."""
        assert CFG.max_daily_loss_pct == 0.020, "Max daily loss must be 0.020 per FR-10-02"

    def test_max_consecutive_losses(self):
        """SC-08: Max consecutive losses = 3."""
        assert CFG.max_consecutive_losses == 3, "Max consecutive losses must be 3 per FR-10-03"

    def test_max_drawdown_pct(self):
        """Max drawdown = 3% from peak."""
        assert CFG.max_drawdown_pct == 0.030, "Max drawdown must be 0.030 per FR-10-04"

    def test_absolute_ceiling_pct(self):
        """Absolute ceiling per trade = 1%."""
        assert CFG.absolute_ceiling_pct == 0.010, "Absolute ceiling must be 0.010 per FR-10-05"

    # =========================================================================
    # TRADE SETUP THRESHOLDS (FR-07)
    # =========================================================================

    def test_min_rr_ratio(self):
        """SC-09: Minimum R:R ratio = 1.5."""
        assert CFG.min_rr_ratio == 1.5, "Min R:R must be 1.5 per FR-07-08"

    def test_max_cushion_ticks(self):
        """Max cushion = 10 ticks."""
        assert CFG.max_cushion_ticks == 10, "Max cushion must be 10 per FR-07-05"

    def test_cushion_excellent_ticks(self):
        """Excellent cushion = ≤3 ticks."""
        assert CFG.cushion_excellent_ticks == 3, "Excellent cushion must be 3 per FR-07-05"

    def test_cushion_acceptable_ticks(self):
        """Acceptable cushion = ≤6 ticks."""
        assert CFG.cushion_acceptable_ticks == 6, "Acceptable cushion must be 6 per FR-07-05"

    # =========================================================================
    # PARTITION EXIT THRESHOLDS (FR-08)
    # =========================================================================

    def test_p1_pct(self):
        """P1 exit = 30% of position."""
        assert CFG.p1_pct == 0.30, "P1 must be 30% per FR-08-01"

    def test_p1_trigger_r(self):
        """P1 trigger at 33% of R."""
        assert CFG.p1_trigger_r == 0.33, "P1 trigger must be 33% R per FR-08-01"

    def test_p2_pct(self):
        """P2 exit = 50% of position."""
        assert CFG.p2_pct == 0.50, "P2 must be 50% per FR-08-03"

    def test_p3_pct(self):
        """P3 exit = 20% of position."""
        assert CFG.p3_pct == 0.20, "P3 must be 20% per FR-08-04"

    def test_breakeven_trigger_r(self):
        """Break-even trigger at 35% of R."""
        assert CFG.breakeven_trigger_r == 0.35, "BE trigger must be 35% R per FR-08-07"

    def test_trail_remaining_pct(self):
        """Trail remaining percentage = 40%."""
        assert CFG.trail_remaining_pct == 0.40, "Trail pct must be 0.40 per FR-08-08"

    def test_counter_aggression_exit_count(self):
        """Counter-aggression exit = 2+ signals."""
        assert CFG.counter_aggression_exit_count == 2, "Counter-agg exit must be 2 per FR-08-06"

    # =========================================================================
    # PYRAMID THRESHOLDS (FR-09)
    # =========================================================================

    def test_max_pyramid_adds(self):
        """Max pyramid adds = 2."""
        assert CFG.max_pyramid_adds == 2, "Max pyramid adds must be 2 per FR-09-02"

    def test_pyramid_add1_size(self):
        """Pyramid add 1 = 100% of base."""
        assert CFG.pyramid_add1_size == 1.0, "Pyramid add 1 must be 100% per FR-09-05"

    def test_pyramid_add2_size(self):
        """Pyramid add 2 = 50% of base."""
        assert CFG.pyramid_add2_size == 0.5, "Pyramid add 2 must be 50% per FR-09-05"

    # =========================================================================
    # MARKET STATE THRESHOLDS (FR-04)
    # =========================================================================

    def test_poc_no_trade_ticks(self):
        """NO_TRADE zone = ±2 ticks from POC."""
        assert CFG.poc_no_trade_ticks == 2, "POC no-trade must be 2 ticks per FR-04-01"

    def test_displacement_multiplier(self):
        """Displacement = ATR × 1.5."""
        assert CFG.displacement_multiplier == 1.5, "Displacement must be 1.5 per FR-04-04"

    # =========================================================================
    # AGGRESSION SIGNAL WEIGHTS (FR-06)
    # =========================================================================

    def test_aggression_footprint_weight(self):
        """Footprint signal weight = +1.0."""
        assert CFG.aggression_footprint_weight == 1.0, "Footprint weight must be 1.0 per FR-06-01"

    def test_aggression_cvd_weight(self):
        """CVD signal weight = +1.0."""
        assert CFG.aggression_cvd_weight == 1.0, "CVD weight must be 1.0 per FR-06-02"

    def test_aggression_big_trade_weight(self):
        """Big trade signal weight = +1.0."""
        assert CFG.aggression_big_trade_weight == 1.0, "Big trade weight must be 1.0 per FR-06-03"

    def test_aggression_absorption_weight(self):
        """Absorption signal weight = +0.5."""
        assert CFG.aggression_absorption_weight == 0.5, "Absorption weight must be 0.5 per FR-06-04"

    def test_aggression_ofi_weight(self):
        """OFI signal weight = +0.5."""
        assert CFG.aggression_ofi_weight == 0.5, "OFI weight must be 0.5 per FR-06-05"

    def test_aggression_confluence_weight(self):
        """Confluence signal weight = +0.5."""
        assert CFG.aggression_confluence_weight == 0.5, "Confluence weight must be 0.5 per FR-06-06"

    def test_aggression_bubble_weight(self):
        """Bubble signal weight = +0.5."""
        assert CFG.aggression_bubble_weight == 0.5, "Bubble weight must be 0.5 per FR-06-07"

    # =========================================================================
    # SUM VERIFICATION
    # =========================================================================

    def test_max_aggression_score(self):
        """Max aggression score = 5.0 (1+1+1+0.5+0.5+0.5+0.5)."""
        max_score = (
            CFG.aggression_footprint_weight +
            CFG.aggression_cvd_weight +
            CFG.aggression_big_trade_weight +
            CFG.aggression_absorption_weight +
            CFG.aggression_ofi_weight +
            CFG.aggression_confluence_weight +
            CFG.aggression_bubble_weight
        )
        assert max_score == 5.0, f"Max aggression must be 5.0, got {max_score}"
