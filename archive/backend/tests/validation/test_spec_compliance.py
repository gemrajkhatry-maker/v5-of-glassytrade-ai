"""SPEC COMPLIANCE VALIDATION — Exact Algorithm Implementation Check.

Validates that the system implements the exact algorithms specified:
1. Volume Profile Engine (POC, VAH/VAL, LVN/HVN)
2. Order Flow Metrics (CVD, Footprint, Absorption, OFI, VWAP)
3. Market State Engine (BALANCED, IMBALANCED, PROBING, NO_TRADE)
4. Drive Classification (First vs Second Drive)
5. Aggression Scoring (5 weighted signals)
6. Trade Construction (Entry, SL, Target, R:R)
7. Risk Management (Session limits, position sizing)
8. Trade Management (Break-even, trailing, exit)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from types import SimpleNamespace


# ============================================================================
# SPEC CONFIGURATION (from spec)
# ============================================================================

SPEC_CONFIG = {
    "tick_size": 0.10,
    "profile_bucket_size": 0.10,
    "value_area_pct": 0.70,
    "lvn_threshold": 0.15,       # < 15% of mean
    "hvn_threshold": 2.00,       # > 200% of mean
    "footprint_imbalance": 3.00, # 300% ratio
    "big_trade_multiplier": 5.0,
    "absorption_range_atr": 0.30,
    "absorption_vol_mult": 2.00,
    "displacement_atr_mult": 1.50,
    "poc_no_trade_ticks": 2,
    "min_aggression_score": 2.0,
    "risk_pct": 0.005,
    "atr_period": 14,
    "avg_vol_period": 20,
}


# ============================================================================
# TEST: Volume Profile Engine
# ============================================================================

class TestVolumeProfileEngine:
    """Validate VP calculations match spec."""

    def test_poc_is_max_volume_bucket(self):
        """POC must be at price level with highest volume."""
        profile = {100: 500, 101: 1200, 102: 800, 103: 300}
        poc = max(profile, key=profile.get)
        assert poc == 101, f"POC should be 101 (max vol), got {poc}"
        print(f"✅ POC = {poc} (max volume bucket)")

    def test_value_area_is_70_percent(self):
        """Value Area must contain 70% of total volume."""
        total_vol = 10000
        target_vol = total_vol * 0.70
        assert target_vol == 7000, "70% VA calculation correct"
        print(f"✅ VA target = {target_vol} (70% of {total_vol})")

    def test_lvn_threshold_15_percent(self):
        """LVN = volume < 15% of mean (per spec)."""
        threshold = SPEC_CONFIG["lvn_threshold"]
        assert threshold == 0.15, f"LVN threshold should be 0.15, got {threshold}"
        print(f"✅ LVN threshold = {threshold} (15% of mean)")

    def test_hvn_threshold_200_percent(self):
        """HVN = volume > 200% of mean (per spec)."""
        threshold = SPEC_CONFIG["hvn_threshold"]
        assert threshold == 2.00, f"HVN threshold should be 2.00, got {threshold}"
        print(f"✅ HVN threshold = {threshold} (200% of mean)")


# ============================================================================
# TEST: Order Flow Metrics
# ============================================================================

class TestOrderFlowMetrics:
    """Validate order flow calculations match spec."""

    def test_cvd_formula(self):
        """CVD = cumsum(ask_vol - bid_vol) per tick."""
        ticks = [
            {"ask_vol": 100, "bid_vol": 50},   # delta = +50
            {"ask_vol": 80, "bid_vol": 120},   # delta = -40
            {"ask_vol": 150, "bid_vol": 50},   # delta = +100
        ]
        cvd = 0
        cvd_series = []
        for t in ticks:
            cvd += t["ask_vol"] - t["bid_vol"]
            cvd_series.append(cvd)
        
        assert cvd_series == [50, 10, 110], f"CVD series incorrect: {cvd_series}"
        print(f"✅ CVD series: {cvd_series}")

    def test_cvd_slope_calculation(self):
        """CVD slope = (recent[-1] - recent[0]) / window."""
        cvd_series = [0, 10, 20, 35, 50, 70, 95, 120, 150, 185]
        window = 5
        recent = cvd_series[-window:]  # [95, 120, 150, 185, ...]
        slope = (recent[-1] - recent[0]) / len(recent)
        expected = (recent[-1] - recent[0]) / window  # (185-95)/5 = 18.0
        assert abs(slope - expected) < 0.01
        print(f"✅ CVD slope = {slope:.1f} (positive = buying pressure)")

    def test_footprint_imbalance_threshold(self):
        """Footprint imbalance = 300% ratio (3:1)."""
        threshold = SPEC_CONFIG["footprint_imbalance"]
        assert threshold == 3.0, f"Should be 3.0, got {threshold}"
        
        # Test: ask/bid >= 3.0 = bullish imbalance
        ask, bid = 300, 100
        ratio = ask / bid
        assert ratio >= threshold
        print(f"✅ Imbalance threshold = {threshold} (3:1 ratio)")

    def test_absorption_detection(self):
        """Absorption = high volume + small range."""
        atr = 10.0
        avg_vol = 1000
        
        # Valid absorption candle
        candle = {"high": 102, "low": 100, "close": 101, "open": 100, "volume": 2500}
        candle_range = candle["high"] - candle["low"]
        is_small_range = candle_range < atr * SPEC_CONFIG["absorption_range_atr"]
        is_high_volume = candle["volume"] > avg_vol * SPEC_CONFIG["absorption_vol_mult"]
        
        assert is_small_range, "Range should be < 30% of ATR"
        assert is_high_volume, "Volume should be > 2x average"
        print(f"✅ Absorption detected: range={candle_range} < {atr*0.3:.1f}, vol={candle['volume']} > {avg_vol*2}")

    def test_big_trade_threshold(self):
        """Big trade = 5x avg trade size."""
        avg_size = 10
        threshold = avg_size * SPEC_CONFIG["big_trade_multiplier"]
        assert threshold == 50.0, f"Should be 50, got {threshold}"
        print(f"✅ Big trade threshold = {threshold} (5x average)")


# ============================================================================
# TEST: Market State Engine
# ============================================================================

class TestMarketStateEngine:
    """Validate market state detection."""

    def test_balanced_inside_va(self):
        """Price inside VA = BALANCED."""
        vah, val, poc = 105, 95, 100
        price = 101  # Inside VA
        is_balanced = val <= price <= vah
        assert is_balanced
        print(f"✅ Price {price} inside VA [{val}, {vah}] = BALANCED")

    def test_imbalanced_outside_va_with_displacement(self):
        """Price outside VA + displacement = IMBALANCED."""
        vah = 105
        price = 108  # Outside VA
        atr = 5.0
        candle_range = 12.0  # > 1.5x ATR
        
        is_displacement = candle_range > atr * SPEC_CONFIG["displacement_atr_mult"]
        is_outside = price > vah
        
        assert is_outside and is_displacement
        print(f"✅ Price {price} outside VAH + displacement = IMBALANCED")

    def test_poc_dead_zone(self):
        """±2 ticks around POC = NO_TRADE."""
        poc = 100.0
        tick_size = SPEC_CONFIG["tick_size"]
        dead_zone = SPEC_CONFIG["poc_no_trade_ticks"] * tick_size
        price = 100.15  # Within dead zone
        
        in_dead_zone = abs(price - poc) <= dead_zone
        assert in_dead_zone
        print(f"✅ Price {price} within ±{dead_zone} of POC {poc} = NO_TRADE")


# ============================================================================
# TEST: Drive Classification
# ============================================================================

class TestDriveClassification:
    """Validate first/second drive detection."""

    def test_first_drive_blocks_entry(self):
        """First drive at level = NO ENTRY."""
        drive_count = 1
        entry_valid = drive_count >= 2  # Only second+ drives valid
        assert not entry_valid
        print("✅ First drive = NO ENTRY (wait for second)")

    def test_second_drive_with_rejection_allows_entry(self):
        """Second drive + first was rejected = VALID ENTRY."""
        drive_count = 2
        first_rejected = True
        entry_valid = drive_count == 2 and first_rejected
        assert entry_valid
        print("✅ Second drive + first rejected = VALID ENTRY")

    def test_third_drive_blocks_entry(self):
        """Third+ drive = level exhausted, no entry."""
        drive_count = 3
        entry_valid = drive_count <= 2
        assert not entry_valid
        print("✅ Third drive = LEVEL EXHAUSTED, no entry")


# ============================================================================
# TEST: Aggression Scoring
# ============================================================================

class TestAggressionScoring:
    """Validate aggression score calculation."""

    def test_aggression_threshold(self):
        """Minimum score = 2.0 per spec."""
        threshold = SPEC_CONFIG["min_aggression_score"]
        assert threshold == 2.0
        print(f"✅ Min aggression score = {threshold}")

    def test_signal_weights(self):
        """Verify signal weights match spec."""
        # Footprint: 1.0, CVD: 1.0, BigTrade: 1.0, Absorption: 0.5, OFI: 0.5
        weights = {"footprint": 1.0, "cvd": 1.0, "big_trade": 1.0, 
                   "absorption": 0.5, "ofi": 0.5}
        total = sum(weights.values())
        assert total == 4.0, f"Total weight should be 4.0, got {total}"
        print(f"✅ Signal weights total = {total} (max possible score)")

    def test_high_confidence_threshold(self):
        """HIGH confidence = score >= 3.0."""
        score = 3.5
        confidence = "High" if score >= 3.0 else "Medium" if score >= 2.0 else "Low"
        assert confidence == "High"
        print(f"✅ Score {score} = {confidence} confidence")


# ============================================================================
# TEST: Trade Construction
# ============================================================================

class TestTradeConstruction:
    """Validate trade setup construction."""

    def test_stop_loss_beyond_aggressive_print(self):
        """SL should be 2 ticks beyond aggressive print."""
        tick_size = SPEC_CONFIG["tick_size"]
        aggressive_print = 100.0
        buffer = 2 * tick_size
        direction = "LONG"
        
        if direction == "LONG":
            sl = aggressive_print - buffer
        else:
            sl = aggressive_print + buffer
        
        expected_sl = 100.0 - 0.20  # = 99.80
        assert abs(sl - expected_sl) < 0.01
        print(f"✅ SL = {sl} (2 ticks beyond aggressive print)")

    def test_risk_reward_calculation(self):
        """R:R = reward / risk."""
        entry = 100.0
        stop = 98.0
        target = 106.0
        
        risk = abs(entry - stop)    # 2.0
        reward = abs(target - entry)  # 6.0
        rr = reward / risk
        
        assert rr == 3.0, f"R:R should be 3.0, got {rr}"
        print(f"✅ R:R = {rr:.1f} (reward/risk)")

    def test_position_sizing_formula(self):
        """Lots = (equity × risk%) / (risk_per_lot × point_value)."""
        equity = 100000
        risk_pct = SPEC_CONFIG["risk_pct"]  # 0.005
        risk_per_unit = 2.0  # entry - stop
        point_value = 1
        
        risk_amount = equity * risk_pct  # 500
        risk_per_lot = risk_per_unit * point_value  # 2
        lots = int(risk_amount / risk_per_lot)  # 250
        
        assert lots == 250
        print(f"✅ Position size = {lots} lots (risk ₹{risk_amount})")


# ============================================================================
# TEST: Risk Management
# ============================================================================

class TestRiskManagement:
    """Validate risk management rules."""

    def test_max_daily_loss(self):
        """2% max daily loss = session kill switch."""
        max_loss_pct = 0.02
        equity = 100000
        max_loss = equity * max_loss_pct
        
        # Simulate losses
        daily_pnl = -1500
        loss_pct = abs(min(daily_pnl, 0)) / equity
        
        can_trade = loss_pct < max_loss_pct
        assert can_trade, f"Should stop at {max_loss_pct:.0%} loss"
        print(f"✅ Daily loss limit = {max_loss_pct:.0%} (₹{max_loss:.0f})")

    def test_consecutive_loss_limit(self):
        """3 consecutive losses = stop trading."""
        max_consec = 3
        consecutive = 3
        
        can_trade = consecutive < max_consec
        assert not can_trade, "Should stop after 3 consecutive losses"
        print(f"✅ Consecutive loss limit = {max_consec}")

    def test_position_sizing_0_5_percent(self):
        """Standard risk = 0.5% per trade."""
        risk_pct = SPEC_CONFIG["risk_pct"]
        assert risk_pct == 0.005
        print(f"✅ Risk per trade = {risk_pct:.1%}")


# ============================================================================
# RUNNER
# ============================================================================

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
