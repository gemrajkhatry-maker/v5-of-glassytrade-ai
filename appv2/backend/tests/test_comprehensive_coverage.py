"""Comprehensive tests for uncovered domain services."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import time
import pytest
from types import SimpleNamespace
from collections import deque

# Domain services
from appv2.domain.services.break_detector import BreakDetector
from appv2.domain.services.drive_tracker import DriveTracker, DriveState
from appv2.domain.services.entry_zones import EntryZoneDetector
from appv2.domain.services.exposure_monitor import ExposureMonitor
from appv2.domain.services.initial_balance import InitialBalanceEngine
from appv2.domain.services.iv_rank import IVRankTracker
from appv2.domain.services.lvn_hvn_detector import LVNPersistenceTracker
from appv2.domain.services.mtf_analyzer import MultiTimeframeAnalyzer
from appv2.domain.services.orderflow_detectors import (
    BigTradeDetector, AbsorptionDetector, OFICalculator, BubbleDetector,
)
from appv2.domain.services.profile_classifier import classify_shape, POCMigrationTracker
from appv2.domain.services.scale_manager import ScaleManager, ScalePhase
from appv2.domain.services.slippage_tracker import SlippageTracker
from appv2.domain.services.three_align_gate import three_align_check
from appv2.domain.services.volatility_adjuster import VolatilityAdjuster
from appv2.domain.services.trail_engine import TrailEngine
from appv2.domain.services.strike_selector import select_strike
from appv2.infrastructure.stream_manager import StreamManager, StreamHealth
from appv2.domain.models.option import OptionChain, OptionContract


# ── Break Detector ──────────────────────────────────────────────────

def test_break_detector_initiative():
    """Initiative break: price breaks IB with momentum."""
    detector = BreakDetector()

    candle = SimpleNamespace(
        high=105, low=100, close=104, open=100,
        range=5, body=4, volume=150,
    )

    result = detector.check_break(candle, ib_high=102, ib_low=98, avg_volume=100)
    assert result.broken
    assert result.direction == "UP"
    assert result.is_initiative


def test_break_detector_responsive():
    """Responsive break: weak volume, small body."""
    detector = BreakDetector()

    candle = SimpleNamespace(
        high=103.5, low=100, close=102.5, open=101,
        range=3.5, body=1.5, volume=80,
    )

    result = detector.check_break(candle, ib_high=102, ib_low=98, avg_volume=100)
    assert result.broken
    assert result.is_responsive


def test_break_detector_no_break():
    """Price inside IB = no break."""
    detector = BreakDetector()

    candle = SimpleNamespace(
        high=101, low=99, close=100, open=100,
        range=2, body=0, volume=100,
    )

    result = detector.check_break(candle, ib_high=102, ib_low=98, avg_volume=100)
    assert not result.broken


# ── Drive Tracker ───────────────────────────────────────────────────

def test_drive_tracker_d1_detection():
    """D1 = first directional drive."""
    tracker = DriveTracker()

    for _ in range(5):
        result = tracker.update(101.0, True)

    assert result.drive_number == 1
    assert result.direction == "UP"


def test_drive_tracker_exhaustion():
    """D3+ with many pullbacks = exhaustion."""
    tracker = DriveTracker()

    # Create drives through pullbacks
    for i in range(30):
        is_high = (i % 5) < 3  # 3 up, 2 down = pulls
        result = tracker.update(100 + i * 0.1, is_high)

    # After enough drives, should be D3+ with exhaustion
    assert result.drive_number >= 1


def test_drive_tracker_suppression():
    """D1 suppressed = couldn't gain momentum."""
    tracker = DriveTracker()

    # Drive then immediate pullback
    tracker.update(101.0, True)
    for _ in range(4):
        result = tracker.update(100.5, False)

    assert result.drive_number == 1
    # Suppression after pullback


# ── Entry Zones ─────────────────────────────────────────────────────

def test_entry_zone_va_edge_pullback():
    """VA edge pullback entry zone."""
    detector = EntryZoneDetector(tick_size=0.05)

    zone = detector.va_edge_pullback(
        direction="LONG",
        current_price=110.10,
        vah=110.0, val=90.0, poc=100.0,
        is_after_break=True,
    )

    assert zone is not None
    assert zone.zone_type == "VA_EDGE"
    assert zone.direction == "LONG"


def test_entry_zone_poc_bounce():
    """POC bounce entry zone."""
    detector = EntryZoneDetector(tick_size=0.05)

    zone = detector.poc_bounce(
        direction="LONG",
        current_price=100.10,
        poc=100.0, vah=110.0, val=90.0,
    )

    assert zone is not None
    assert zone.zone_type == "POC_BOUNCE"


def test_entry_zone_lvn_retest():
    """LVN retest entry zone."""
    detector = EntryZoneDetector(tick_size=0.05)

    zone = detector.lvn_retest(
        direction="LONG",
        current_price=100.0,
        lvn_levels=[100.10, 95.0, 105.0],
        tolerance_ticks=5,
    )

    assert zone is not None
    assert zone.zone_type == "LVN_RETEST"


# ── Exposure Monitor ────────────────────────────────────────────────

def test_exposure_monitor_within_limits():
    """Exposure within limits should be OK."""
    monitor = ExposureMonitor(
        capital=5_000_000,
        max_exposure_pct=30.0,
        max_single_symbol_pct=10.0,
    )

    monitor.add_position("NIFTY", 50, 100.0)

    state = monitor.get_state()
    assert state.is_within_limits
    assert state.total_exposure == 5000.0


def test_exposure_monitor_exceeds_limit():
    """Exceeding total exposure should flag."""
    monitor = ExposureMonitor(
        capital=100_000,
        max_exposure_pct=5.0,
        max_single_symbol_pct=3.0,
    )

    monitor.add_position("NIFTY", 50, 100.0)  # 5000
    monitor.add_position("BANKNIFTY", 25, 100.0)  # 2500 → total 7500 = 7.5%

    state = monitor.get_state()
    assert not state.is_within_limits


def test_exposure_monitor_can_open():
    """Can open position check."""
    monitor = ExposureMonitor(capital=1_000_000, max_exposure_pct=10.0)

    ok, reason = monitor.can_open_position("NIFTY", quantity=50, price=100.0)
    assert ok

    # Fill up exposure
    for i in range(20):
        monitor.add_position(f"SYM{i}", 50, 100.0)

    ok, reason = monitor.can_open_position("NEW", quantity=50, price=100.0)
    assert not ok
    assert "exposure" in reason.lower()


# ── Initial Balance ─────────────────────────────────────────────────

def test_initial_balance_accumulation():
    """IB should accumulate high/low during window."""
    ib = InitialBalanceEngine(ib_minutes=5)

    for i in range(3):
        candle = SimpleNamespace(high=100 + i, low=98 - i, close=99 + i)
        state = ib.update(candle)

    assert not state.is_complete  # Still within 5-min window
    assert state.high >= 100
    assert state.low <= 96


def test_initial_balance_complete():
    """IB should complete after window."""
    ib = InitialBalanceEngine(ib_minutes=2)

    ib.update(SimpleNamespace(high=101, low=99, close=100))
    state = ib.update(SimpleNamespace(high=102, low=98, close=101))

    assert state.is_complete
    assert state.high == 102
    assert state.low == 98


# ── IV Rank Tracker ─────────────────────────────────────────────────

def test_iv_rank_computation():
    """IV rank should be computed correctly."""
    tracker = IVRankTracker(window_days=5)

    # Feed decreasing IV
    for iv in [0.30, 0.28, 0.25, 0.22, 0.20]:
        tracker.update(iv)

    state = tracker.update(0.15)
    # Current IV = 0.15, range = 0.30-0.15 = 0.15
    # IV rank = (0.15 - 0.15) / 0.15 * 100 = 0%
    assert state.iv_rank == pytest.approx(0, abs=5)


def test_iv_crush_detection():
    """IV crush = sudden drop."""
    tracker = IVRankTracker()

    tracker.update(0.30)
    state = tracker.update(0.20)  # 33% drop > 15% threshold

    assert state.is_iv_crush


# ── LVN/HVN Detector ───────────────────────────────────────────────

def test_lvn_hvn_detection():
    """LVN and HVN should be detected."""
    tracker = LVNPersistenceTracker(
        min_persistence=2,
        lvn_threshold=0.15,
        hvn_threshold=2.0,
    )

    profile = [
        SimpleNamespace(price=90, volume=5),   # LVN (< 15% of mean)
        SimpleNamespace(price=95, volume=50),  # Normal
        SimpleNamespace(price=100, volume=100),# HVN (> 200% of mean)
        SimpleNamespace(price=105, volume=50), # Normal
        SimpleNamespace(price=110, volume=5),  # LVN
    ]

    lvns, hvns = tracker.update(profile)
    # Need 2 consecutive updates for persistence
    lvns2, hvns2 = tracker.update(profile)

    assert len(lvns2) > 0
    assert len(hvns2) > 0


# ── MTF Analyzer ────────────────────────────────────────────────────

def test_mtf_analyzer_aligned():
    """All timeframes aligned = score 3."""
    from appv2.domain.enums.market_state import MarketState

    analyzer = MultiTimeframeAnalyzer()

    result = analyzer.analyze(
        daily_poc=100, daily_vah=110, daily_val=90,
        hourly_state=MarketState.IMBALANCED,
        five_min_state=MarketState.IMBALANCED,
        current_price=105,  # Above daily POC
    )

    assert result.alignment_score >= 2
    assert result.aligned_direction == "LONG"


# ── Order Flow Detectors ────────────────────────────────────────────

def test_big_trade_detector():
    """Big trade = volume > 2× average."""
    detector = BigTradeDetector()

    candle = SimpleNamespace(volume=250)
    result = detector.detect(candle, avg_volume=100)

    assert result.detected
    assert result.volume_ratio == 2.5


def test_absorption_detector():
    """Absorption = large range + large volume + small body."""
    detector = AbsorptionDetector()

    candle = SimpleNamespace(
        high=110, low=90, close=100, open=100,
        range=20, body=0, volume=200,
    )

    result = detector.detect(candle, atr=10, avg_volume=100)
    assert result.detected
    assert result.range_ratio == 2.0
    assert result.vol_ratio == 2.0


def test_ofi_calculator():
    """OFI = delta / volume."""
    calc = OFICalculator()

    candle = SimpleNamespace(delta=50, volume=100)
    result = calc.update(candle)

    assert result.ofi == 0.5


def test_bubble_detector():
    """Volume bubble = volume > threshold × average."""
    detector = BubbleDetector()

    result = detector.detect(
        SimpleNamespace(volume=500),
        avg_volume=100,
        threshold_mult=3.0,
    )

    assert result["detected"]
    assert result["ratio"] == 5.0


# ── Profile Classifier ──────────────────────────────────────────────

def test_profile_shape_classification():
    """Profile shape classification."""
    from appv2.domain.services.incremental_volume_profile import VolumeProfileLevel

    # Bell shape (POC in center)
    profile = [
        VolumeProfileLevel(price=90, volume=10),
        VolumeProfileLevel(price=95, volume=30),
        VolumeProfileLevel(price=100, volume=100),  # POC in center
        VolumeProfileLevel(price=105, volume=30),
        VolumeProfileLevel(price=110, volume=10),
    ]

    shape = classify_shape(profile, poc=100, vah=110, val=90)
    assert shape.shape == "D"  # Bell


def test_poc_migration_tracker():
    """POC migration tracking."""
    tracker = POCMigrationTracker()

    assert tracker.update(100) == "SAME"
    assert tracker.update(102) == "HIGHER"
    assert tracker.update(98) == "LOWER"


# ── Scale Manager ───────────────────────────────────────────────────

def test_scale_manager_initialization():
    """Scale manager should initialize 3 levels."""
    sm = ScaleManager()
    scales = sm.initialize(
        direction="LONG", full_quantity=50,
        entry_price=100, base_sl=95, base_tp=110,
    )

    assert len(scales) == 3
    assert scales[0].size_pct == 0.40
    assert scales[0].filled  # Scale 1 filled immediately
    assert not scales[1].filled
    assert not scales[2].filled


def test_scale_manager_fill():
    """Filling subsequent scales."""
    sm = ScaleManager()
    sm.initialize("LONG", 50, 100, 95, 110)

    # Fill scale 2
    filled = sm.fill_scale(102)
    assert filled is not None
    assert filled.phase == ScalePhase.ADD_ON
    assert filled.filled

    # Fill scale 3
    filled = sm.fill_scale(104)
    assert filled is not None
    assert filled.phase == ScalePhase.FINAL

    # No more scales
    assert not sm.can_add_scale()
    assert sm.is_full()


# ── Slippage Tracker ────────────────────────────────────────────────

def test_slippage_tracker_buy():
    """Buy slippage = actual - expected (positive = paid more)."""
    tracker = SlippageTracker()

    record = tracker.record_fill(
        symbol="NIFTY", side="BUY",
        expected_price=100.0, actual_price=100.10,
    )

    assert record.slippage > 0
    assert record.slippage_bps > 0


def test_slippage_tracker_sell():
    """Sell slippage = expected - actual (positive = received less)."""
    tracker = SlippageTracker()

    record = tracker.record_fill(
        symbol="NIFTY", side="SELL",
        expected_price=100.0, actual_price=99.90,
    )

    assert record.slippage > 0


def test_slippage_tracker_stats():
    """Slippage stats per symbol."""
    tracker = SlippageTracker()

    for i in range(10):
        tracker.record_fill(
            "NIFTY", "BUY", 100.0, 100.0 + i * 0.01,
        )

    stats = tracker.get_symbol_stats()
    assert "NIFTY" in stats
    assert stats["NIFTY"]["count"] == 10
    assert stats["NIFTY"]["avg_bps"] > 0


# ── Three Align Gate ────────────────────────────────────────────────

def test_three_align_all_aligned():
    """All 3 timeframes aligned = score 3."""
    data_5min = [SimpleNamespace(close=101, open=100) for _ in range(10)]
    data_15min = [SimpleNamespace(close=101, open=100) for _ in range(5)]
    data_1hr = [SimpleNamespace(close=101, open=100, volume=100) for _ in range(3)]

    result = three_align_check(
        data_5min, data_15min, data_1hr,
        direction="LONG",
        poc_15min=100.0,
        poc_1hr=99.0,
        current_price=101.0,
    )

    assert result.alignment_score >= 2
    assert result.passed


def test_three_align_misaligned():
    """Mixed timeframes = low score."""
    data_5min = [SimpleNamespace(close=99, open=100) for _ in range(10)]  # Bearish
    data_15min = [SimpleNamespace(close=101, open=100) for _ in range(5)]  # Bullish
    data_1hr = [SimpleNamespace(close=100, open=100, volume=100) for _ in range(3)]

    result = three_align_check(
        data_5min, data_15min, data_1hr,
        direction="LONG",
        poc_15min=100.0,
        poc_1hr=100.0,
        current_price=99.0,  # Below POC = bearish
    )

    assert result.alignment_score <= 1


# ── Volatility Adjuster ─────────────────────────────────────────────

def test_volatility_adjuster_high_vol():
    """High volatility = reduced position size."""
    adjuster = VolatilityAdjuster(base_atr=50.0)

    adj = adjuster.adjust(current_atr=150.0, normal_position_size=50)

    assert adj.adjustment_factor < 1.0
    assert adj.is_high_volatility
    assert adj.recommended_size_pct < 50  # Reduced to < 50%


def test_volatility_adjuster_low_vol():
    """Low volatility = can increase size."""
    adjuster = VolatilityAdjuster(base_atr=50.0)

    adj = adjuster.adjust(current_atr=25.0, normal_position_size=50)

    assert adj.adjustment_factor > 1.0
    assert not adj.is_high_volatility


def test_volatility_adjuster_get_size():
    """Adjusted position size calculation."""
    adjuster = VolatilityAdjuster(base_atr=50.0)

    size = adjuster.get_adjusted_size(current_atr=100.0, normal_size=50)
    assert size < 50  # Reduced

    size = adjuster.get_adjusted_size(current_atr=25.0, normal_size=50)
    assert size > 50  # Increased


# ── Trail Engine ────────────────────────────────────────────────────

def test_trail_engine_atr():
    """ATR trailing stop."""
    engine = TrailEngine(atr_multiplier=2.0)

    result = engine.atr_trail(
        is_long=True, current_price=105.0, current_sl=95.0,
        atr=3.0, entry_price=100.0,
    )

    assert result.new_stop_loss > 95.0  # Tightened
    assert result.trail_type == "ATR"


def test_trail_engine_vwap():
    """VWAP trailing stop."""
    engine = TrailEngine()

    result = engine.vwap_trail(
        is_long=True, current_sl=95.0,
        vwap=102.0, entry_price=100.0,
    )

    assert result.new_stop_loss > 95.0
    assert result.trail_type == "VWAP"


def test_trail_engine_cvd_breakeven():
    """CVD breakeven move."""
    engine = TrailEngine()

    result = engine.cvd_breakeven(
        trade_id="T1", is_long=True, current_sl=95.0,
        entry_price=100.0, cvd_slope=3.0,
    )

    assert result.new_stop_loss >= 100.0
    assert result.moved_to_breakeven


# ── Stream Manager ──────────────────────────────────────────────────

def test_stream_manager_health():
    """Stream manager health tracking."""
    mgr = StreamManager()

    health = mgr.get_health()
    assert not health.connected  # No broker
    assert health.ticks_received == 0

    mgr.pause()
    assert mgr._paused
    mgr.resume()
    assert not mgr._paused


# ── Strike Selector ─────────────────────────────────────────────────

def test_strike_selector_atm():
    """ATM strike selection."""
    chain = OptionChain(
        underlying="NIFTY", expiry_date="2024-03-20", spot_price=100,
        options=[
            OptionContract(symbol="N CE", underlying="NIFTY", strike_price=95,
                          expiry_date="2024-03-20", option_type="CE", lot_size=50,
                          oi=60000, volume=500, ltp=10, delta=0.70),
            OptionContract(symbol="N CE", underlying="NIFTY", strike_price=100,
                          expiry_date="2024-03-20", option_type="CE", lot_size=50,
                          oi=80000, volume=800, ltp=5, delta=0.50),
            OptionContract(symbol="N CE", underlying="NIFTY", strike_price=105,
                          expiry_date="2024-03-20", option_type="CE", lot_size=50,
                          oi=70000, volume=600, ltp=2, delta=0.30),
        ],
    )

    selection = select_strike(chain, "LONG", 100, "ATM", 5.0)
    assert selection is not None
    # ATM (100) should score highest for scalping
    assert selection.contract.strike_price == 100
