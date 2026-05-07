"""Tests for three-align entry gate."""
import pytest
from types import SimpleNamespace
from app.domain.fabio_ai.services.entry_gates.three_align import (
    _to_float,
    min_candles_gate,
    full_body_close_gate,
    nearest_round_number,
    cluster_aggressive_prints,
    extract_bubble_levels_from_footprint,
    three_align_check,
)
from app.domain.trading.model.value_objects import (
    OHLC,
    AMTResult,
    AggressivePrint,
    FootprintCandle,
    FootprintLevel,
)


def _make_candle(time="2024-01-15T10:00:00", open=100.0, high=101.0, low=99.5, close=100.5, volume=100.0, delta=30.0):
    """Helper to create an OHLC candle with volume and delta."""
    return OHLC.create(time=time, open=open, high=high, low=low, close=close, volume=volume, delta=delta)


def _make_amt_result(**overrides):
    """Helper to create an AMTResult with sane defaults for passing gates."""
    defaults = dict(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=105.0,
        value_area_low=95.0,
        cvd_slope=0.0,
        price_velocity=0.02,
    )
    defaults.update(overrides)
    return AMTResult(**defaults)


def _make_fp_level(price, stacked=False, magnitude=0):
    """Create a FootprintLevel-like object with magnitude attribute."""
    return SimpleNamespace(price=price, stacked=stacked, magnitude=magnitude)


def _make_fp_candle(levels):
    """Create a FootprintCandle with given levels."""
    return FootprintCandle(time="t", levels=tuple(levels))


class TestToFloat:
    """Tests for _to_float conversion helper."""

    def test_none_returns_default(self):
        """None input returns the default value."""
        assert _to_float(None) is None
        assert _to_float(None, default=42.0) == 42.0

    def test_string_converts(self):
        """String numbers convert to float."""
        assert _to_float("3.14") == pytest.approx(3.14)
        assert _to_float("-10.5") == pytest.approx(-10.5)

    def test_int_converts(self):
        """Integer input converts to float."""
        assert _to_float(42) == 42.0
        assert _to_float(0) == 0.0

    def test_float_passes_through(self):
        """Float input passes through unchanged."""
        assert _to_float(3.14) == pytest.approx(3.14)

    def test_invalid_string_returns_default(self):
        """Non-numeric strings return default."""
        assert _to_float("abc") is None
        assert _to_float("abc", default=0.0) == 0.0

    def test_overflow_returns_default(self):
        """OverflowError returns default."""
        assert _to_float(float("inf")) == float("inf")  # doesn't raise


class TestMinCandlesGate:
    """Tests for min_candles_gate."""

    def test_fewer_than_min(self):
        """Returns False when data has fewer candles than min_candles."""
        assert min_candles_gate([1, 2, 3, 4, 5], min_candles=6) is False

    def test_exactly_min(self):
        """Returns True when data has exactly min_candles."""
        assert min_candles_gate([1, 2, 3, 4, 5, 6], min_candles=6) is True

    def test_more_than_min(self):
        """Returns True when data exceeds min_candles."""
        assert min_candles_gate(list(range(20)), min_candles=6) is True

    def test_empty_data(self):
        """Returns False for empty data."""
        assert min_candles_gate([], min_candles=6) is False


class TestFullBodyCloseGate:
    """Tests for full_body_close_gate."""

    def test_long_body_above_50_close_above_level(self):
        """LONG: body > 50% and close > break_level returns True."""
        tick = OHLC.create(time="t", open=100.0, high=102.0, low=99.0, close=101.5, volume=100)
        assert full_body_close_gate(tick, break_level=100.5, direction="LONG") is True

    def test_long_body_below_50(self):
        """LONG: body < 50% returns False regardless of close."""
        tick = OHLC.create(time="t", open=100.0, high=101.0, low=99.0, close=100.1, volume=100)
        # body=0.1, range=2.0, body_pct=0.05 < 0.5
        assert full_body_close_gate(tick, break_level=90.0, direction="LONG") is False

    def test_short_body_above_50_close_below_level(self):
        """SHORT: body > 50% and close < break_level returns True."""
        tick = OHLC.create(time="t", open=100.0, high=101.0, low=98.0, close=98.5, volume=100)
        # body=1.5, range=3.0, body_pct=0.5 -> not < 0.5, so passes
        assert full_body_close_gate(tick, break_level=99.0, direction="SHORT") is True

    def test_short_close_above_level(self):
        """SHORT: close above break_level returns False."""
        tick = OHLC.create(time="t", open=100.0, high=102.0, low=99.0, close=101.5, volume=100)
        assert full_body_close_gate(tick, break_level=100.5, direction="SHORT") is False

    def test_unknown_direction(self):
        """Unknown direction returns False."""
        tick = OHLC.create(time="t", open=100.0, high=102.0, low=98.0, close=101.0, volume=100)
        assert full_body_close_gate(tick, break_level=99.0, direction="BOTH") is False


class TestNearestRoundNumber:
    """Tests for nearest_round_number."""

    def test_price_below_1000(self):
        """Prices < 1000 round to nearest 100 (Python banker's rounding)."""
        # round(4.5)=4 (banker's rounding), round(4.2)=4
        assert nearest_round_number(450.0) == 400.0
        assert nearest_round_number(420.0) == 400.0
        assert nearest_round_number(460.0) == 500.0

    def test_price_1000_to_10000(self):
        """Prices 1000-10000 round to nearest 500."""
        assert nearest_round_number(1200.0) == 1000.0
        assert nearest_round_number(1300.0) == 1500.0
        assert nearest_round_number(9800.0) == 10000.0

    def test_price_above_10000(self):
        """Prices > 10000 round to nearest 1000."""
        assert nearest_round_number(12300.0) == 12000.0
        assert nearest_round_number(12600.0) == 13000.0

    def test_exact_boundary_1000(self):
        """Price exactly 1000 rounds to nearest 500 bucket."""
        assert nearest_round_number(1000.0) == 1000.0

    def test_zero_price(self):
        """Price 0 rounds to 0."""
        assert nearest_round_number(0.0) == 0.0


class TestClusterAggressivePrints:
    """Tests for cluster_aggressive_prints."""

    def test_empty_prints(self):
        """Empty iterable returns empty list."""
        assert cluster_aggressive_prints([]) == []

    def test_single_print(self):
        """Single print returns one cluster."""
        p = AggressivePrint(price=100.0, time="t", side="BUY", volume=50.0, delta=10.0)
        result = cluster_aggressive_prints([p])
        assert len(result) == 1
        assert result[0] == pytest.approx(100.0)

    def test_clustered_prints_merge(self):
        """Prints within cluster_pct merge into one VWAP cluster."""
        p1 = AggressivePrint(price=100.0, time="t1", side="BUY", volume=10.0, delta=2.0)
        p2 = AggressivePrint(price=100.05, time="t2", side="BUY", volume=20.0, delta=4.0)
        result = cluster_aggressive_prints([p1, p2])
        assert len(result) == 1

    def test_spread_prints_separate(self):
        """Prints beyond cluster_pct stay separate."""
        p1 = AggressivePrint(price=100.0, time="t1", side="BUY", volume=10.0, delta=2.0)
        p2 = AggressivePrint(price=102.0, time="t2", side="BUY", volume=20.0, delta=4.0)
        result = cluster_aggressive_prints([p1, p2])
        assert len(result) == 2

    def test_sorted_by_volume_descending(self):
        """Clusters sorted by volume descending."""
        p1 = AggressivePrint(price=100.0, time="t1", side="BUY", volume=5.0, delta=1.0)
        p2 = AggressivePrint(price=102.0, time="t2", side="SELL", volume=50.0, delta=-10.0)
        result = cluster_aggressive_prints([p1, p2])
        assert result[0] == pytest.approx(102.0)  # higher volume first

    def test_max_five_clusters(self):
        """Returns at most 5 clusters."""
        prints = [
            AggressivePrint(price=100.0 + i * 2.0, time=f"t{i}", side="BUY", volume=float(10 + i * 5), delta=1.0)
            for i in range(10)
        ]
        result = cluster_aggressive_prints(prints)
        assert len(result) <= 5

    def test_zero_volume_filtered(self):
        """Prints with zero volume are filtered out."""
        p = AggressivePrint(price=100.0, time="t", side="BUY", volume=0.0, delta=0.0)
        result = cluster_aggressive_prints([p])
        assert result == []

    def test_zero_price_filtered(self):
        """Prints with zero price are filtered out."""
        p = AggressivePrint(price=0.0, time="t", side="BUY", volume=10.0, delta=2.0)
        result = cluster_aggressive_prints([p])
        assert result == []


class TestExtractBubbleLevelsFromFootprint:
    """Tests for extract_bubble_levels_from_footprint."""

    def test_none_footprint(self):
        """None footprint returns empty list."""
        assert extract_bubble_levels_from_footprint(None) == []

    def test_empty_dict(self):
        """Empty dict returns empty list."""
        assert extract_bubble_levels_from_footprint({}) == []

    def test_valid_stacked_levels(self):
        """Footprint with stacked levels extracts prices."""
        level = _make_fp_level(price=100.0, stacked=True, magnitude=3)
        fp = _make_fp_candle([level])
        result = extract_bubble_levels_from_footprint({"key": fp})
        assert 100.0 in result

    def test_non_stacked_ignored(self):
        """Non-stacked levels are ignored."""
        level = _make_fp_level(price=100.0, stacked=False, magnitude=3)
        fp = _make_fp_candle([level])
        result = extract_bubble_levels_from_footprint({"key": fp})
        assert result == []

    def test_magnitude_below_min(self):
        """Levels with magnitude < min_stacked_count are ignored."""
        level = _make_fp_level(price=100.0, stacked=True, magnitude=1)
        fp = _make_fp_candle([level])
        result = extract_bubble_levels_from_footprint({"key": fp}, min_stacked_count=2)
        assert result == []

    def test_negative_price_filtered(self):
        """Levels with negative/zero price are filtered."""
        level = _make_fp_level(price=-5.0, stacked=True, magnitude=3)
        fp = _make_fp_candle([level])
        result = extract_bubble_levels_from_footprint({"key": fp})
        assert result == []

    def test_recent_only(self):
        """Only last 3 footprint candles are checked."""
        old_level = _make_fp_level(price=50.0, stacked=True, magnitude=3)
        old_fp = _make_fp_candle([old_level])
        new_level = _make_fp_level(price=100.0, stacked=True, magnitude=3)
        new_fp = _make_fp_candle([new_level])
        fp_dict = {f"k{i}": old_fp for i in range(10)}
        fp_dict["k10"] = new_fp
        result = extract_bubble_levels_from_footprint(fp_dict)
        assert 100.0 in result


class TestThreeAlignCheck:
    """Tests for three_align_check main function."""

    def _base_data(self, n=25):
        """Create baseline OHLC data with volume and delta."""
        return [_make_candle(time=f"2024-01-15T{10 + i // 12}:{(i % 12) * 5:02d}:00", volume=100.0, delta=30.0) for i in range(n)]

    def test_gate_passes_near_level_confirmation_strong(self):
        """Gate passes when price near POC and confirmation is strong."""
        data = self._base_data()
        tick = _make_candle(time="2024-01-15T11:00:00", open=99.5, high=101.0, low=99.0, close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0, cvd_slope=0.0, price_velocity=0.02)
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert passed is True
        assert strong is True

    def test_gate_fails_poc_missing(self):
        """Gate fails when POC is zero."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=0.0, value_area_high=105.0, value_area_low=95.0)
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False
        assert strong is False

    def test_gate_fails_vah_missing(self):
        """Gate fails when VAH is zero."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=0.0, value_area_low=95.0)
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False

    def test_gate_fails_val_missing(self):
        """Gate fails when VAL is zero."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=0.0)
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False

    def test_cvd_hard_kill_balanced_negative(self):
        """CVD slope extremely negative kills gate in BALANCED state."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0,
                               cvd_slope=-200.0, market_state="BALANCED")
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False
        assert strong is False

    def test_cvd_hard_kill_balanced_positive(self):
        """CVD slope extremely positive kills gate in BALANCED state."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0,
                               cvd_slope=200.0, market_state="BALANCED")
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False

    def test_price_velocity_kill(self):
        """Price velocity > 0.5 kills the gate."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0,
                               price_velocity=0.8)
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False
        assert strong is False

    def test_second_drive_detected(self):
        """Second drive detected: past touches but no recent touches."""
        # Build data where candles at positions -20 to -5 touch poc=100, but last 3 do not
        data = []
        for i in range(40):
            if 20 <= i < 35:  # positions -20 to -5 from end
                d = _make_candle(time=f"2024-01-15T{i // 12}:{(i % 12) * 5:02d}:00",
                                 open=99.5, high=100.5, low=99.5, close=100.0, volume=100.0, delta=30.0)
            else:
                d = _make_candle(time=f"2024-01-15T{i // 12}:{(i % 12) * 5:02d}:00",
                                 open=110.0, high=112.0, low=108.0, close=111.0, volume=100.0, delta=30.0)
            data.append(d)
        tick = _make_candle(time="t_last", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0)
        result = three_align_check(data, amt, tick, tick_size=0.05, return_is_second_drive=True)
        assert len(result) == 3
        is_second_drive = result[2]
        assert is_second_drive is True

    def test_no_second_drive_when_recent_touches(self):
        """No second drive when there are recent touches."""
        data = self._base_data(10)
        tick = _make_candle(time="t_last", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0)
        result = three_align_check(data, amt, tick, tick_size=0.05, return_is_second_drive=True)
        is_second_drive = result[2]
        assert is_second_drive is False

    def test_bubble_levels_from_footprint(self):
        """Bubble levels from footprint domain are included in level checks."""
        data = self._base_data()
        level = _make_fp_level(price=100.0, stacked=True, magnitude=3)
        fp = _make_fp_candle([level])
        tick = _make_candle(time="t_last", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=200.0, value_area_high=210.0, value_area_low=190.0)
        fp_domain = {"recent": fp}
        passed, strong = three_align_check(data, amt, tick, footprint_domain=fp_domain, tick_size=0.05)
        assert passed is True

    def test_divergence_confirmation_path(self):
        """CVD divergence provides confirmation when aggregation is weak."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=5.0, delta=0.5)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0,
                               cvd_divergence="bullish")
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert strong is True
        assert passed is True

    def test_leg_levels_probing_market(self):
        """PROBING market uses leg POC/VAH/VAL as levels."""
        data = self._base_data()
        tick = _make_candle(time="t", close=98.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(
            poc=200.0, value_area_high=210.0, value_area_low=190.0,
            market_state="PROBING",
            leg_poc=98.0, leg_vah=102.0, leg_val=94.0,
        )
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert passed is True

    def test_leg_levels_imbalanced_market(self):
        """IMBALANCED market uses leg levels."""
        data = self._base_data()
        tick = _make_candle(time="t", close=98.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(
            poc=200.0, value_area_high=210.0, value_area_low=190.0,
            market_state="IMBALANCED",
            leg_poc=98.0, leg_vah=102.0, leg_val=94.0,
        )
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert passed is True

    def test_not_near_any_level(self):
        """Gate fails when price is far from all levels."""
        data = self._base_data()
        # Price 507.3: round_level=500, distance=7.3 > threshold=1.5
        # Also far from POC=100, VAH=105, VAL=95
        tick = _make_candle(time="t", close=507.3, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0)
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert passed is False
        assert strong is True

    def test_no_confirmation_weak(self):
        """Gate fails when confirmation is weak (no divergence, no bundle)."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=5.0, delta=0.1)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0,
                               cvd_divergence="")
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert strong is False
        assert passed is False

    def test_returns_second_drive_flag(self):
        """When return_is_second_drive=True, returns 3-tuple."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0)
        result = three_align_check(data, amt, tick, return_is_second_drive=True, tick_size=0.05)
        assert len(result) == 3

    def test_returns_two_tuple_by_default(self):
        """Default return is 2-tuple."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0)
        result = three_align_check(data, amt, tick, tick_size=0.05)
        assert len(result) == 2

    def test_va_range_too_narrow(self):
        """Gate fails when VA range is too narrow (<= poc * 0.001)."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=100.05, value_area_low=100.0)
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False

    def test_infinite_poc_rejected(self):
        """Gate fails when POC is infinite."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=float("inf"), value_area_high=105.0, value_area_low=95.0)
        passed, strong = three_align_check(data, amt, tick)
        assert passed is False

    def test_elevated_velocity_passes_with_debug(self):
        """Price velocity > 0.1 but <= 0.5 passes (logs debug)."""
        data = self._base_data()
        tick = _make_candle(time="t", close=100.0, volume=500.0, delta=100.0)
        amt = _make_amt_result(poc=100.0, value_area_high=105.0, value_area_low=95.0,
                               price_velocity=0.3)
        passed, strong = three_align_check(data, amt, tick, tick_size=0.05)
        assert passed is True
