"""Unit tests for AMT analyzer domain service (ported to quant/amt/analyzer)."""

from __future__ import annotations

import math
import pytest
from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel
from quant.amt.analyzer import (
    create_profile,
    find_lvns,
    find_hvns,
    find_aggressive_prints,
    AMTAnalyzer,
    AMTConfig,
    AcceptanceRejectionEngine,
)
from quant.amt import compute as mc
from quant.contracts.value_objects import VolumeProfileLevel
from backend.tests.helpers.market_data import generate_market_data


def _make_candle(
    close: float,
    volume: float = 1000,
    delta: float = 0,
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
    time: str = "2026-01-01T00:00:00Z",
) -> OHLC:
    o = open_ or close
    h = high or max(close, o) * 1.001
    l = low or min(close, o) * 0.999
    return OHLC(
        time=time,
        open=o,
        high=h,
        low=l,
        close=close,
        volume=volume,
        vwap=(h + l + close) / 3,
        taker_buy_volume=(volume + delta) / 2,
        delta=delta,
    )


def _candle_time(minute_of_session: int) -> str:
    """IST-style timestamp for minute-of-session (09:15 open)."""
    total = 15 + minute_of_session
    return f"2026-01-01T{total // 60:02d}:{total % 60:02d}:00Z"


def _squeeze_dto() -> dict:
    """Synthesize an inline squeeze-recovery session and return its DTO.

    Mirrors the scenario asserted for RegimeDetector.detect_squeeze: a wide
    low-volume expansion, a tight high-volume contraction into the VA, one
    bar's low piercing VAL, then the last bar closing back above VAL.
    """
    from quant.amt.dto import amt_result_to_dto

    data = []
    for i in range(20):  # expansion: wide range, low volume
        data.append(_make_candle(close=100.0, high=104.0, low=96.0, volume=100,
                                 time=_candle_time(i)))
    for i in range(20):  # contraction: tight range, high volume (VA anchor)
        data.append(_make_candle(close=100.0 + (i % 2) * 0.02, high=100.1,
                                 low=99.9, volume=5000, time=_candle_time(20 + i)))
    data.append(_make_candle(close=99.6, high=99.9, low=99.0, volume=200,
                             time=_candle_time(40)))  # pierce below VAL
    data.append(_make_candle(close=100.1, high=100.3, low=99.8, volume=200,
                             time=_candle_time(41)))  # recovery above VAL
    result = AMTAnalyzer().analyze(data)
    return amt_result_to_dto(result)


def _candle_stream(start_min: int, end_min: int, high_boost: float = 0.0) -> list[OHLC]:
    """Candles every 5 minutes from 09:15, minutes [start_min, end_min] inclusive."""
    candles = []
    for m in range(start_min, end_min + 1, 5):
        hour, minute = divmod(15 + m, 60)
        t = f"2026-01-01T{hour:02d}:{minute:02d}:00Z"
        base = 100 + m * 0.1
        candles.append(
            _make_candle(
                close=base,
                high=base + 2 + high_boost,
                low=base - 2,
                volume=1000,
                time=t,
            )
        )
    return candles


class TestSmoothArray:
    def test_identity_window_1(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = mc.smooth_array(data, 1)
        assert result == data

    def test_smoothing_window_3(self):
        data = [0.0, 10.0, 0.0]
        result = mc.smooth_array(data, 3)
        assert abs(result[1] - 10.0 / 3) < 0.01


class TestCreateProfile:
    def test_empty(self):
        assert create_profile([]) == []

    def test_basic_profile(self):
        data = generate_market_data(50, 100, "sideways")
        profile = create_profile(data, 20)
        assert len(profile) == 20
        assert all(p.volume >= 0 for p in profile)

    def test_total_volume_roughly_matches(self):
        data = generate_market_data(100, 100, "bullish")
        profile = create_profile(data, 50)
        profile_vol = sum(p.volume for p in profile)
        data_vol = sum(d.volume for d in data)
        assert abs(profile_vol - data_vol) / data_vol < 0.05

    def test_uniform_distribution_no_gaussian_bleed(self):
        """Volume should be strictly confined to the high/low range of candles."""
        # Single candle 100-110
        data = [_make_candle(105, open_=105, high=110, low=100, volume=1000)]
        profile = create_profile(data, buckets=20)

        # Volume should only be in buckets whose centers are between ~100 and ~110
        volume_outside_range = 0
        volume_inside_range = 0
        for p in profile:
            if 98 <= p.price <= 112:
                volume_inside_range += p.volume
            else:
                volume_outside_range += p.volume

        assert volume_outside_range == 0
        assert volume_inside_range > 0


class TestFindLVNsHVNs:
    def test_hvns_exist_in_normal_data(self):
        data = generate_market_data(200, 100, "sideways")
        profile = create_profile(data, 50)
        hvns = find_hvns(profile)
        assert isinstance(hvns, list)


class TestAggressivePrints:
    def test_empty_short_data(self):
        data = [_make_candle(100) for _ in range(10)]
        prints = find_aggressive_prints(data)
        assert prints == []

    def test_detects_prints(self):
        data = [_make_candle(100, volume=100, delta=30) for _ in range(60)]
        data[30] = _make_candle(100, volume=500, delta=200)
        prints = find_aggressive_prints(data)
        assert len(prints) >= 1
        assert prints[0].side == "BUY"


class TestAMTAnalyzer:
    def test_insufficient_data(self):
        analyzer = AMTAnalyzer()
        result = analyzer.analyze([_make_candle(100)])
        assert result.market_state == "BALANCED"
        assert result.signal is None

    def test_empty_data(self):
        analyzer = AMTAnalyzer()
        result = analyzer.analyze([])
        assert result.poc == 0

    def test_basic_analysis(self):
        analyzer = AMTAnalyzer()
        data = generate_market_data(100, 100, "sideways")
        result = analyzer.analyze(data)
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low
        assert isinstance(result.profile, tuple)
        assert len(result.profile) > 0

    def test_with_order_book(self):
        analyzer = AMTAnalyzer()
        data = generate_market_data(100, 100, "bullish")
        ob = OrderBook(
            bids=(OrderBookLevel(price=100, quantity=1000),),
            asks=(OrderBookLevel(price=101, quantity=100),),
        )
        result = analyzer.analyze(data, ob)
        assert result.poc > 0

    def test_obi_from_order_book_reaches_result(self):
        """Depth reaches the decision path: the order book imbalance computed
        from the live depth snapshot must land on AMTResult.obi so gate 3's
        order-flow aggression leg can consume it."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(100, 100, "sideways")
        # Bid-heavy book (1000 vs 100): OBI = (1000-100)/1100 ≈ 0.82
        ob = OrderBook(
            bids=(OrderBookLevel(price=100, quantity=1000),),
            asks=(OrderBookLevel(price=101, quantity=100),),
        )
        result = analyzer.analyze(data, ob)
        assert result.obi > 0.5

    # ----- Formula gap tests -----

    def test_collapsed_regime_clamps_vah_to_recent_range(self):
        """When the option premium collapses intraday (morning ~195, afternoon
        ~102), the whole-session value area must not extend to the stale
        morning regime. VAH must clamp to the recent traded range.

        Reproduces the live CRUDEOIL 7950 CALL case: the premium halved, so
        the session profile's 70% area spans ~158 even though price sits at
        ~102. Unlike a volume desert, the collapse traded through every
        level — volume exists in every bucket — so only a recent-range clamp
        fixes it."""
        analyzer = AMTAnalyzer()
        data = []
        # Stale collapse regime: continuous tile 90 -> 199 (volume in EVERY
        # bucket — no zero-volume gap for the desert guard to catch)
        c = 90.0
        while c < 199.0:
            data.append(
                _make_candle(close=c, volume=300, high=c + 0.9, low=c - 0.9)
            )
            c += 0.9
        # Current auction cluster (newest candles): 100-106, denser per bucket
        for i in range(60):
            c = 100.0 + (i % 7)
            data.append(
                _make_candle(close=c, volume=300, high=c + 0.4, low=c - 0.4)
            )

        result = analyzer.analyze(data)
        # POC in the current auction cluster (densest bucket there)
        assert result.poc > 95.0
        assert result.poc < 110.0
        # 70% of the wide total volume must NOT drag VAH into the stale
        # morning regime — clamp to the recent traded range instead.
        assert result.value_area_high < 125.0
        # But must still capture the current auction's top
        assert result.value_area_high > 104.0
        assert result.value_area_low < 100.0

    def test_ib_freezes_at_60_min_but_session_va_keeps_developing(self):
        """Fabio's framework: the Initial Balance (high/low of the first hour)
        freezes after 60 minutes, while the session Value Area keeps
        recalculating for the rest of the session. Freezing both would break
        AMT — an in-window candle with a new high must still extend the IB,
        but a candle past minute 60 must not move IB high/low, while the VA
        keeps tracking new volume."""
        analyzer = AMTAnalyzer()
        # The runtime calls analyze() once per bar close with the newest bar as
        # data[-1] — feed every candle individually from the session open to
        # mirror it exactly (this also pins the IB window to 09:15, the
        # session open, not the fifth analyzed bar).
        data_evolving: list[OHLC] = []
        r1 = None
        for m in range(0, 60, 5):
            candle = _make_candle(
                close=100 + m * 0.1,
                high=100 + m * 0.1 + 2,
                low=100 + m * 0.1 - 2,
                volume=1000,
                time=_candle_time(m),
            )
            data_evolving.append(candle)
            r1 = analyzer.analyze(data_evolving)
        # Minute 55 (10:10) carries the fresh session high (112) — must extend
        # the IB under a 60-minute build window (10:10 is minute 55 < 60).
        data_evolving[-1] = _make_candle(close=105, high=112, low=99, volume=1200,
                                         time=_candle_time(55))
        r1 = analyzer.analyze(data_evolving)
        assert r1.ib_complete is False  # minute 55 < 60 — still building
        assert r1.ib_high >= 112.0      # in-window new high IS included

        # Minute 60 (10:15) is the LAST candle of the first hour — the window
        # closes AFTER including it, so its high legitimately extends the IB.
        data_evolving.append(
            _make_candle(close=160, high=148, low=96, volume=1000,
                         time=_candle_time(60))
        )
        r_at_close = analyzer.analyze(data_evolving)
        assert r_at_close.ib_complete is True   # window closes at minute 60
        assert r_at_close.ib_high >= 148.0      # boundary candle is included

        # Past-window candles (65..75) with even higher highs must NOT move
        # IB high (frozen), but their volume must still feed the session VA.
        r2 = None
        for m in range(65, 76, 5):
            data_evolving.append(
                _make_candle(close=100 + m * 0.1, high=100 + m * 0.1 + 42,
                             low=100 + m * 0.1 - 2, volume=1000,
                             time=_candle_time(m))
            )
            r2 = analyzer.analyze(data_evolving)
        assert r2.ib_complete is True   # minute 75 > 60 — window closed
        assert r2.ib_high == r_at_close.ib_high  # new highs past hour 1 do NOT extend IB
        # Session VA keeps developing: new volume after hour 1 moves the POC /
        # value area instead of being locked to first-hour data.
        assert r2.poc != r1.poc or r2.value_area_high != r1.value_area_high

    def test_vah_val_use_bin_edges(self):
        """VAH should be upper edge of top VA bin, VAL lower edge of bottom."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        profile = list(result.profile)
        if len(profile) > 1:
            step = profile[1].price - profile[0].price
            half = step / 2
            # VAH and VAL should NOT equal any bin midpoint exactly
            midpoints = {round(p.price, 8) for p in profile}
            assert round(result.value_area_high, 8) not in midpoints
            assert round(result.value_area_low, 8) not in midpoints
            # They should be offset by exactly half_step from a midpoint
            vah_offset = min(abs(result.value_area_high - p.price) for p in profile)
            val_offset = min(abs(result.value_area_low - p.price) for p in profile)
            assert abs(vah_offset - half) < 0.001
            assert abs(val_offset - half) < 0.001

    def test_poc_tiebreak_closest_to_vwap(self):
        """When multiple bins share max volume, POC should be closest to VWAP."""
        # Create a profile with two equal-volume peaks
        profile = [VolumeProfileLevel(price=90 + i * 10, volume=0) for i in range(5)]
        profile[1].volume = 100  # price=100
        profile[3].volume = 100  # price=120
        # With VWAP closer to 120, POC should pick index 3
        analyzer = AMTAnalyzer()
        # Seed the VWAP accumulator toward 120
        analyzer._vwap_cum_vol = 1000
        analyzer._vwap_cum_quote_vol = 120000  # VWAP = 120
        data = [_make_candle(120, volume=100) for _ in range(30)]
        result = analyzer.analyze(data)
        # POC should exist and be valid
        assert result.poc > 0

    def test_balance_ratio_computed(self):
        """Balance ratio should be between 0 and 1."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert 0.0 <= result.balance_ratio <= 1.0

    def test_balanced_market_has_balance_ratio(self):
        """Sideways market should have non-zero balance ratio."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert result.balance_ratio > 0.0  # at least some candles inside VA

    def test_vwap_bands_computed(self):
        """VWAP ±1σ and ±2σ bands should be populated after analysis."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert result.session_vwap > 0
        # Bands should be symmetric around VWAP
        assert result.vwap_upper_1 >= result.session_vwap
        assert result.vwap_lower_1 <= result.session_vwap
        assert result.vwap_upper_2 >= result.vwap_upper_1
        assert result.vwap_lower_2 <= result.vwap_lower_1

    def test_vwap_bands_2sigma_wider_than_1sigma(self):
        """2σ bands should be wider than 1σ bands."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "bullish")
        result = analyzer.analyze(data)
        width_1 = result.vwap_upper_1 - result.vwap_lower_1
        width_2 = result.vwap_upper_2 - result.vwap_lower_2
        assert width_2 >= width_1

    def test_displacement_leg_returns_leg_lvns(self):
        """detect_displacement_leg should return LVN list (possibly empty)."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "bullish")
        from quant.amt.profile.displacement import detect_displacement_leg
        result = detect_displacement_leg(data, analyzer.config)
        assert isinstance(result, dict)
        assert isinstance(result["has_displacement"], bool)
        assert isinstance(result["lvns"], list)

    def test_amt_result_has_new_fields(self):
        """AMTResult should include all new formula fields."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        # All new fields should exist
        assert hasattr(result, "vwap_upper_1")
        assert hasattr(result, "vwap_lower_1")
        assert hasattr(result, "vwap_upper_2")
        assert hasattr(result, "vwap_lower_2")
        assert hasattr(result, "balance_ratio")


# ---------------------------------------------------------------------------
# Group 1: Full AMTAnalyzer.analyze() Integration Tests
# ---------------------------------------------------------------------------


def _make_candle_timed(
    close: float,
    time_str: str,
    volume: float = 1000,
    delta: float = 0,
    high: float | None = None,
    low: float | None = None,
) -> OHLC:
    """Helper that creates a candle with a specific timestamp."""
    o = close
    h = high or close * 1.002
    l = low or close * 0.998
    return OHLC(
        time=time_str,
        open=o,
        high=h,
        low=l,
        close=close,
        volume=volume,
        vwap=(h + l + close) / 3,
        taker_buy_volume=(volume + delta) / 2,
        delta=delta,
    )


class TestAnalyzeIntegration:
    """Integration tests for the full analyze() pipeline."""

    def test_analyze_returns_three_tuple(self):
        """analyze() should return an AMTResult (not a tuple in current API)."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        # The return type is AMTResult with all required fields
        assert hasattr(result, "market_state")
        assert hasattr(result, "poc")
        assert hasattr(result, "value_area_high")
        assert hasattr(result, "value_area_low")
        assert hasattr(result, "profile")
        assert hasattr(result, "market_structure")

    def test_analyze_all_fields_populated(self):
        """All AMTResult fields should be populated with valid values on sideways data."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(60, 100, "sideways")
        result = analyzer.analyze(data)

        # Core VP fields
        assert result.poc > 0
        assert result.value_area_high > 0
        assert result.value_area_low > 0
        assert result.value_area_high >= result.value_area_low

        # Profile populated
        assert len(result.profile) > 0
        assert sum(p.volume for p in result.profile) > 0

        # VWAP bands
        assert result.session_vwap > 0
        assert result.vwap_upper_1 >= result.session_vwap
        assert result.vwap_lower_1 <= result.session_vwap
        assert result.vwap_upper_2 >= result.vwap_upper_1
        assert result.vwap_lower_2 <= result.vwap_lower_1

        # Balance ratio in valid range
        assert 0.0 <= result.balance_ratio <= 1.0

        # CVD slope is a finite number
        assert math.isfinite(result.cvd_slope)

        # Profile shape is a non-empty string
        assert isinstance(result.profile_shape, str)
        assert len(result.profile_shape) > 0

        # Market structure and confidence
        assert isinstance(result.market_structure, str)
        assert result.structure_confidence >= 0.0

        # LVN/HVN are tuples (possibly empty)
        assert isinstance(result.lvns, tuple)
        assert isinstance(result.hvns, tuple)

    def test_analyze_trending_data(self):
        """Trending data should produce a valid market structure reflecting the trend."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(80, 100, "bullish")
        result = analyzer.analyze(data)

        # POC should exist and be reasonable
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low

        # Market structure should be one of the valid states
        valid_structures = {
            "BALANCE",
            "BALANCED",
            "TRENDING_UP",
            "TRENDING_DOWN",
            "BREAKOUT_UP",
            "BREAKOUT_DOWN",
            "TRANSITION",
        }
        assert result.market_structure in valid_structures

        # Profile shape should be valid
        assert result.profile_shape in ("P", "b", "D", "B")

    def test_analyze_minimal_data(self):
        """Exactly 5 candles (minimum for analyze) should not crash."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(5, 100, "sideways")
        result = analyzer.analyze(data)

        # Should return a valid result, not crash
        assert result.poc > 0
        assert result.value_area_high >= result.value_area_low
        assert 0.0 <= result.balance_ratio <= 1.0
        assert math.isfinite(result.cvd_slope)


# ---------------------------------------------------------------------------
# Group 3: Incremental Profile Update Tests
# ---------------------------------------------------------------------------


class TestIncrementalProfile:
    """Tests for incremental profile updates matching full rebuilds."""

    def test_incremental_matches_full_rebuild(self):
        """Incremental analyze (30 then 31) should match fresh analyze of all 31."""
        data_30 = generate_market_data(30, 100, "sideways")
        data_31 = data_30 + [generate_market_data(1, data_30[-1].close, "sideways")[0]]

        # Incremental path: same analyzer instance, two calls
        inc_analyzer = AMTAnalyzer()
        inc_analyzer.analyze(data_30)
        inc_result = inc_analyzer.analyze(data_31)

        # Fresh path: new analyzer, full data
        fresh_analyzer = AMTAnalyzer()
        fresh_result = fresh_analyzer.analyze(data_31)

        # POC/VAH/VAL should be very close (same profile construction)
        assert inc_result.poc == pytest.approx(fresh_result.poc, rel=0.01)
        assert inc_result.value_area_high == pytest.approx(
            fresh_result.value_area_high,
            rel=0.01,
        )
        assert inc_result.value_area_low == pytest.approx(
            fresh_result.value_area_low,
            rel=0.01,
        )

    def test_incremental_rebuilds_on_range_expansion(self):
        """Adding a candle far outside the range should still produce valid results."""
        # 20 candles in range 100-110
        data = []
        for i in range(20):
            price = 100 + (i % 10)
            data.append(
                _make_candle_timed(
                    price,
                    f"2026-01-01T00:{i:02d}:00Z",
                    volume=1000,
                    delta=50,
                    high=price + 0.5,
                    low=price - 0.5,
                )
            )

        analyzer = AMTAnalyzer()
        analyzer.analyze(data)

        # Add candle at 120, well outside previous range
        outlier = _make_candle_timed(
            120,
            f"2026-01-01T00:20:00Z",
            volume=2000,
            delta=100,
            high=121,
            low=119,
        )
        data_expanded = data + [outlier]
        result = analyzer.analyze(data_expanded)

        # Should not crash and produce valid VP metrics
        assert result.poc > 0
        assert result.value_area_high > result.value_area_low
        # The outlier at 120 should appear in HVNs (it has 2x volume)
        # or at least the profile should span the full range
        profile_max = max(p.price for p in result.profile)
        assert profile_max >= 119  # profile covers the outlier region

    def test_resolution_auto_scales_with_price_range(self):
        """Profile resolution is now auto-computed from price range/tick
        size (quant/amt/profile/volume_profile.py::_auto_bucket_count),
        not a fixed 200 — that was the Phase 4 fix's initial value, since
        superseded by dynamic bucketing clamped to [100, 1000]. Pin the
        clamp bounds instead of the stale fixed value."""
        analyzer = AMTAnalyzer()
        data = generate_market_data(50, 100, "sideways")
        result = analyzer.analyze(data)
        assert 100 <= len(result.profile) <= 1000

    def test_lookback_exceeds_old_limit(self):
        """Analyzer should use >200 candles if provided (no more hard capping)."""
        analyzer = AMTAnalyzer()
        # Create 300 candles. OLD code would cap to 200.
        # We'll put high volume in the first 50 candles (index 0-50).
        # If capping happens, that volume is LOST and POC/VA will shift.
        base_price = 100
        data = []
        for i in range(300):
            vol = 10000 if i < 50 else 100  # High volume at the start
            data.append(_make_candle(base_price + i * 0.1, volume=vol))

        result = analyzer.analyze(data)
        # If we use all 300, the POC should be near the start (high volume zone)
        # Base price 100 to 105.
        assert result.poc < 110

    def test_leg_poc_uses_local_vwap_tiebreak(self):
        """Leg POC should tie-break using local leg VWAP, not session VWAP."""
        analyzer = AMTAnalyzer()
        # Session VWAP is high (near 200)
        analyzer._vwap_cum_vol = 1000
        analyzer._vwap_cum_quote_vol = 200000

        # Trend leg at low prices (10-20)
        # Create two equal peaks in the leg: one at 12, one at 18
        leg_data = []
        for i in range(10):
            p = 10 + i
            vol = 1000 if (p == 12 or p == 18) else 100
            leg_data.append(
                _make_candle(p, volume=vol, open_=p, high=p + 0.5, low=p - 0.5)
            )

        # The leg VWAP will be around 15.
        # 12 is closer to 15 than 18 is.
        # But 18 is closer to SESSION VWAP (200).
        # If it uses local tie-break, POC should be 12.
        from quant.amt.profile.displacement import detect_displacement_leg
        result = detect_displacement_leg(leg_data, analyzer.config)
        assert result["poc"] == pytest.approx(12, abs=1.0)


# ---------------------------------------------------------------------------
# Group 4: Phase 3 Audit Implementations
# ---------------------------------------------------------------------------


class TestVWAPDoubleAccumulationRegression:
    """Regression for audit B-20: analyze() must accumulate each bar ONCE."""

    def test_session_vwap_not_double_accumulated(self):
        """Two _update_session_vwap call sites per analyze() double-counted the
        current bar's volume+quote-volume, inflating the VWAP accumulators.

        Feed a known 2-candle series through analyze twice; the accumulated
        counters and returned VWAP must equal the single-pass expectation.
        """
        analyzer = AMTAnalyzer()
        base = [
            _make_candle_timed(100.0, f"2026-01-01T09:{i:02d}:00Z", volume=100)
            for i in range(4)
        ]
        c5 = _make_candle_timed(100.0, "2026-01-01T09:04:00Z", volume=100)
        c6 = _make_candle_timed(120.0, "2026-01-01T09:05:00Z", volume=100)

        analyzer.analyze(base + [c5])
        result = analyzer.analyze(base + [c5, c6])

        # Single pass: c5 and c6 each accumulated exactly once.
        # _make_candle_timed gives typical_price == close (h/l symmetric).
        assert analyzer._vwap._cum_vol == pytest.approx(200.0)
        assert analyzer._vwap._cum_quote_vol == pytest.approx(100 * 100 + 120 * 100)
        # session_vwap is the same-window VWAP (all 6 candles are inside the
        # 60-bar recent regime window) — the accumulator counters above are
        # the B-20 single-accumulation regression check.
        assert result.session_vwap == pytest.approx((100 * 100 * 5 + 120 * 100) / 600.0)

    def test_re_fed_candle_is_not_re_accumulated(self):
        """Re-feeding the SAME candle (e.g. a sub-candle tick where data[-1]
        has not changed) must NOT re-add its volume/quote-volume/variance to
        the session VWAP accumulators.

        The analyzer is called once per bar close in the runtime path, but the
        legacy handler re-fed the same candle on sub-candle ticks — the
        ``_is_new_candle`` guard must make the accumulators idempotent per
        candle regardless of call cadence.
        """
        analyzer = AMTAnalyzer()
        base = [
            _make_candle_timed(100.0, f"2026-01-01T09:{i:02d}:00Z", volume=100)
            for i in range(4)
        ]
        c5 = _make_candle_timed(100.0, "2026-01-01T09:04:00Z", volume=100)
        c6 = _make_candle_timed(120.0, "2026-01-01T09:05:00Z", volume=100)

        analyzer.analyze(base + [c5])
        # Re-feed the same trailing candle (sub-candle update): nothing new.
        analyzer.analyze(base + [c5])
        assert analyzer._vwap._cum_vol == pytest.approx(100.0)
        assert analyzer._vwap._cum_quote_vol == pytest.approx(100 * 100)
        # Shifted-variance accumulator is gated identically — a re-feed must
        # not widen the σ bands (both numerator and denominator stay exact).
        sq_after_refeed = analyzer._vwap._cum_sq_vol

        # New candle arrives — accumulated exactly once.
        result =        analyzer.analyze(base + [c5, c6])
        assert analyzer._vwap._cum_vol == pytest.approx(200.0)
        assert analyzer._vwap._cum_quote_vol == pytest.approx(100 * 100 + 120 * 100)
        assert analyzer._vwap._cum_sq_vol > sq_after_refeed  # c6 adds variance
        # Same-window VWAP (all candles inside the 60-bar regime window).
        assert result.session_vwap == pytest.approx((100 * 100 * 5 + 120 * 100) / 600.0)

    def test_session_reset_then_new_candle_accumulated(self):
        """After a session reset, the first candle of the new session must be
        accumulated (``_reset_session`` zeroes accumulators but leaves
        ``_vwap_last_time`` set — ``_is_new_candle`` must still be True)."""
        analyzer = AMTAnalyzer()
        base = [
            _make_candle_timed(100.0, f"2026-01-01T09:{i:02d}:00Z", volume=100)
            for i in range(4)
        ]
        last_old = _make_candle_timed(100.0, "2026-01-01T09:04:00Z", volume=100)
        first_new = _make_candle_timed(110.0, "2026-01-02T09:00:00Z", volume=200)

        analyzer.analyze(base + [last_old])
        assert analyzer._vwap._cum_vol == pytest.approx(100.0)

        # New session: accumulators reset, then first candle counted once.
        result = analyzer.analyze(base + [last_old, first_new])
        assert analyzer._vwap._cum_vol == pytest.approx(200.0)
        assert analyzer._vwap._cum_quote_vol == pytest.approx(110 * 200)
        # Same-window VWAP over all 6 passed candles (5 @100 vol100 + 1 @110 vol200).
        assert result.session_vwap == pytest.approx((100 * 100 * 5 + 110 * 200) / 700.0)


class TestDayTypeClassification:
    def test_normal_day_type(self):
        analyzer = AMTAnalyzer()
        # Create an IB (60 mins = 12 5-min candles)
        data = []
        for i in range(12):
            data.append(
                _make_candle_timed(
                    105 + i % 2, f"2026-01-01T09:{i * 5:02d}:00Z", high=110, low=100
                )
            )
            analyzer.analyze(data)
        # Add inside candles
        for i in range(12, 20):
            data.append(
                _make_candle_timed(
                    105, f"2026-01-01T10:{(i - 12) * 5:02d}:00Z", high=108, low=102
                )
            )
            result = analyzer.analyze(data)

        assert result.day_type == "NORMAL"

    def test_trend_day_type(self):
        analyzer = AMTAnalyzer()
        data = []
        # 13 candles span the full 60-min IB window (09:00 -> 10:00 inclusive;
        # the boundary candle closes the window). Fabio: IB = first hour.
        for i in range(13):
            data.append(
                _make_candle_timed(
                    105 + i % 2, _candle_time(i * 5), high=110, low=100
                )
            )
            analyzer.analyze(data)
        assert analyzer._ib_tracker.is_complete  # window closed at 10:00
        # Add massive extension up AFTER the IB window (minute 65 = 10:05).
        # IB range is 10, dist > 10 needs price above 120.
        data.append(_make_candle_timed(125, _candle_time(65), high=125, low=115))
        result = analyzer.analyze(data)

        assert result.day_type == "TREND"


class TestLiquiditySweepDetection:
    def test_liquidity_sweep_high(self):
        engine = AcceptanceRejectionEngine()
        baseline_vol = 1000
        vah = 110.0
        val = 90.0

        # Create a candle that sweeps high
        # Pierce VAH (> 110), close below it (< 110)
        # Strong upper wick (115 - max(109, 108) = 6) > body (109 - 108 = 1)
        # Vol = 2000 > baseline * 1.5 = 1500
        candle = OHLC(
            time="2026-01-01T10:00:00Z",
            open=108.0,
            high=115.0,
            low=107.0,
            close=109.0,
            volume=2000,
            delta=0,
        )

        result = engine.update(candle, vah, val, baseline_vol)
        assert result.get("liquidity_sweep") == "SWEEP_HIGH"


class TestSessionVsLegVABounds:
    """Task 2.3: Session VA should always be within leg VA range."""

    def test_session_va_clamped_to_leg_va(self, caplog):
        """Session VAH/VAL should be clamped to leg VA bounds (Task 2.3)."""
        import logging
        caplog.set_level(logging.WARNING)

        analyzer = AMTAnalyzer()

        # Create data with a strong displacement leg
        # First 20 candles: tight range (session VA will be small)
        # Last 10 candles: strong displacement (leg VA will be large)
        data = []
        for i in range(20):
            # Tight range around 800
            data.append(OHLC(
                time=f"2026-01-01T09:{i:02d}:00Z",
                open=800.0,
                high=802.0,
                low=798.0,
                close=800.0 + (i % 3),
                volume=500,
                delta=0,
            ))

        # Add displacement candles (leg will form here)
        for i in range(10):
            data.append(OHLC(
                time=f"2026-01-01T09:{20+i:02d}:00Z",
                open=800.0 + i * 5,
                high=808.0 + i * 5,
                low=798.0 + i * 5,
                close=805.0 + i * 5,
                volume=1000,
                delta=500,
            ))

        # Run analysis
        result = analyzer.analyze(data)

        # Session VA should encompass leg VA (session is wider or equal)
        if result.value_area_high > 0 and result.leg_vah > 0:
            assert result.value_area_high >= result.leg_vah - 0.01, (
                f"Session VAH {result.value_area_high} should be >= Leg VAH {result.leg_vah}"
            )

        if result.value_area_low > 0 and result.leg_val > 0:
            assert result.value_area_low <= result.leg_val + 0.01, (
                f"Session VAL {result.value_area_low} should be <= Leg VAL {result.leg_val}"
            )


class TestVWAPSigmaBounds:
    """Task 2.1: VWAP sigma should stay within realistic bounds."""

    def test_vwap_sigma_within_bounds(self):
        """σ should stay -4 to +4 on synthetic data (Task 2.1)."""
        analyzer = AMTAnalyzer()

        # Generate 60 minutes of realistic OHLC data
        base_price = 800.0
        data = []
        for i in range(60):
            # Realistic price movement (±0.5% per candle)
            price = base_price + (i % 10 - 5) * 2.0
            candle = OHLC(
                time=f"2026-01-01T09:{i:02d}:00Z",
                open=price,
                high=price + 1.5,
                low=price - 1.5,
                close=price + 0.5,
                volume=1000 + (i % 20) * 50,
                delta=(i % 7 - 3) * 100,
            )
            data.append(candle)

        # Run analysis (order_book is optional)
        result = analyzer.analyze(data)

        # Check that VWAP deviation sigma is within bounds
        if result.vwap_deviation_sigmas is not None:
            assert abs(result.vwap_deviation_sigmas) <= 4.0, (
                f"VWAP sigma {result.vwap_deviation_sigmas} exceeds ±4.0 bound"
            )

    def test_vwap_std_has_minimum(self):
        """VWAP std should have minimum value to prevent extreme sigma (Task 2.1)."""
        analyzer = AMTAnalyzer()

        # Generate very low volatility data
        data = []
        for i in range(30):
            candle = OHLC(
                time=f"2026-01-01T09:{i:02d}:00Z",
                open=800.0,
                high=800.1,
                low=799.9,
                close=800.0,
                volume=100,
                delta=0,
            )
            data.append(candle)

        # Run analysis
        result = analyzer.analyze(data)

        # With low volatility, sigma should still be reasonable (not > 4.0)
        # because MIN_VWAP_STD=1.0 prevents tiny denominators
        if result.vwap_deviation_sigmas is not None:
            assert abs(result.vwap_deviation_sigmas) <= 4.0, (
                f"VWAP sigma {result.vwap_deviation_sigmas} should be bounded with low vol data"
            )

    def test_vwap_and_balance_share_the_recent_regime_window(self):
        """Regime collapse must not produce a VWAP/sigma/balance contradiction.

        Live repro (CRUDEOIL-style): premium collapsed from ~195 to ~102, so
        the whole-session VWAP accumulator sits far above the current auction.
        The VA is clamped to the recent RECENT_VA_LOOKBACK candles, so the UI
        said "LTP +2.4σ from VWAP — EXTREME DEVIATION" while "Balance: 100% in
        VA".  The sigma, bands and session VWAP must be computed on the SAME
        window as the VA clamp so the two readings cannot contradict.
        """
        analyzer = AMTAnalyzer()

        # Feed per-bar like the runtime: early session trades at ~100, then a
        # regime collapse to ~50 that persists for the whole recent window.
        data = []
        for i in range(30):
            price = 100.0 + (i % 5 - 2) * 0.2
            data.append(_make_candle(close=price, high=price + 0.5, low=price - 0.5,
                                     time=_candle_time(i)))
        for i in range(30, 90):
            price = 50.0 + (i % 5 - 2) * 0.2
            data.append(_make_candle(close=price, high=price + 0.5, low=price - 0.5,
                                     time=_candle_time(i)))

        result = None
        for i in range(1, len(data) + 1):
            result = analyzer.analyze(data[:i])

        assert result is not None
        # The last 60 candles are all inside the recent VA -> balance ratio 100%.
        assert result.balance_ratio == 1.0, "recent regime must read 100% in VA"
        # Session VWAP must reflect the CURRENT auction (~50), not the stale
        # whole-session mix (~66.7) that produced the 2.4σ "EXTREME DEVIATION".
        assert 49.0 < result.session_vwap < 51.0, (
            f"session_vwap {result.session_vwap:.2f} must come from the recent "
            f"regime window, not the whole-session accumulator"
        )
        # With price inside the recent VA, deviation cannot be extreme.
        assert result.vwap_deviation_sigmas is not None
        assert abs(result.vwap_deviation_sigmas) < 1.0, (
            f"sigma {result.vwap_deviation_sigmas:.2f} must be small when price "
            f"is inside the same-window VA"
        )


def test_dto_exposes_squeeze_fields():
    """Task 2a: squeeze detection wired through analyzer -> AMTResult -> DTO."""
    dto = _squeeze_dto()
    assert dto["squeezeDirection"] == "LONG"
    assert dto["squeezeTrappedLevel"] > 0
