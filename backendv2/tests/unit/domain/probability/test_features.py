"""Tests for feature extraction in the first-passage probability model."""
from __future__ import annotations

import pytest
from decimal import Decimal

from app.domain.probability.features import (
    FEATURE_NAMES,
    PROBABILITY_FEATURE_SCHEMA_VERSION,
    extract_features,
    extract_features_from_row,
    active_model_features,
)
from app.domain.trading.model.value_objects import (
    OHLC,
    AMTResult,
    OrderBook,
    OrderBookLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlc(time: str = "2025-01-06 09:15:00", open: float = 100,
               high: float = 101, low: float = 99, close: float = 100.5,
               volume: float = 1000, delta: float = 200) -> OHLC:
    return OHLC.create(
        time=time, open=open, high=high, low=low, close=close,
        volume=volume, delta=delta,
    )


def _make_amt_result(**kwargs) -> AMTResult:
    defaults = dict(
        poc=100.0,
        value_area_high=102.0,
        value_area_low=98.0,
        cvd_slope=0.5,
        aggression=0.3,
        profile_shape="D",
        market_state="BALANCED",
        balance_ratio=0.6,
        hvns=(99.0, 101.0),
        lvns=(97.0, 103.0),
    )
    defaults.update(kwargs)
    return AMTResult(**defaults)


def _make_data(n: int = 25, base_time: str = "2025-01-06 09:15:00") -> list[OHLC]:
    """Create n OHLC bars with incrementing times."""
    from datetime import datetime, timedelta
    base = datetime(2025, 1, 6, 9, 15)
    data = []
    for i in range(n):
        t = base + timedelta(minutes=5 * i)
        o = 100.0 + i * 0.1
        data.append(OHLC.create(
            time=t.isoformat(),
            open=o,
            high=o + 1.0,
            low=o - 1.0,
            close=o + 0.5,
            volume=1000.0 + i * 10,
            delta=200.0 + i * 5,
        ))
    return data


def _make_order_book() -> OrderBook:
    bids = tuple(OrderBookLevel(price=99.90 - i * 0.05, quantity=100.0 - i * 5) for i in range(20))
    asks = tuple(OrderBookLevel(price=100.10 + i * 0.05, quantity=90.0 + i * 5) for i in range(20))
    return OrderBook(bids=bids, asks=asks)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFeatureSchema:
    """Verify the feature schema contract."""

    def test_feature_count_is_42(self):
        """FEATURE_NAMES contains exactly 42 features."""
        assert len(FEATURE_NAMES) == 42

    def test_schema_version(self):
        """Schema version is set."""
        assert PROBABILITY_FEATURE_SCHEMA_VERSION == "fp-42-v1"

    def test_feature_names_are_unique(self):
        """All feature names are distinct."""
        assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))


class TestBasicFeatureExtraction:
    """Test basic extract_features() behaviour."""

    def test_returns_dict_with_expected_keys(self):
        """extract_features() returns a dict with all FEATURE_NAMES keys plus diagnostics."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(time="2025-01-06T10:00:00")
        features = extract_features(data, amt, tick)

        # All FEATURE_NAMES must be present; book_imbalance_l20 is also included
        # as a runtime diagnostic feature.
        assert set(FEATURE_NAMES).issubset(set(features.keys()))
        assert "book_imbalance_l20" in features

    def test_all_values_are_floats(self):
        """All feature values are floats."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(time="2025-01-06T10:00:00")
        features = extract_features(data, amt, tick)

        for name, value in features.items():
            assert isinstance(value, float), f"{name} is {type(value)}"

    def test_zero_close_returns_all_zeros(self):
        """When tick.close <= 0, all features are 0.0."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = OHLC.create(
            time="2025-01-06T10:00:00", open=0, high=0, low=0, close=0, volume=0,
        )
        features = extract_features(data, amt, tick)

        for name, value in features.items():
            assert value == 0.0, f"{name} should be 0.0, got {value}"


class TestMicrostructureFeatures:
    """Group A: Price microstructure features."""

    def test_close_vs_poc_pct(self):
        """close_vs_poc_pct = (close - poc) / close."""
        data = _make_data(25)
        amt = _make_amt_result(poc=98.0)
        tick = _make_ohlc(close=100.0)
        features = extract_features(data, amt, tick)

        expected = (100.0 - 98.0) / 100.0
        assert features["close_vs_poc_pct"] == pytest.approx(expected)

    def test_close_vs_vah_val_pct(self):
        """close_vs_vah_pct and close_vs_val_pct computed correctly."""
        data = _make_data(25)
        amt = _make_amt_result(value_area_high=102.0, value_area_low=98.0)
        tick = _make_ohlc(close=100.0)
        features = extract_features(data, amt, tick)

        assert features["close_vs_vah_pct"] == pytest.approx((100.0 - 102.0) / 100.0)
        assert features["close_vs_val_pct"] == pytest.approx((100.0 - 98.0) / 100.0)

    def test_bar_range_and_body(self):
        """bar_range_pct and body_pct use tick OHLC values."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(open=100.0, high=102.0, low=98.0, close=101.0)
        features = extract_features(data, amt, tick)

        close = 101.0
        bar_range = 102.0 - 98.0  # 4.0
        assert features["bar_range_pct"] == pytest.approx(bar_range / close)
        assert features["body_pct"] == pytest.approx(abs(101.0 - 100.0) / close)

    def test_wick_ratios_sum_with_close_position(self):
        """upper_wick + lower_wick + body = 1.0; close_position_in_range in [0,1]."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(open=100.0, high=104.0, low=96.0, close=102.0)
        features = extract_features(data, amt, tick)

        bar_range = 104.0 - 96.0  # 8.0
        upper_wick = (104.0 - 102.0) / bar_range  # 0.25
        lower_wick = (100.0 - 96.0) / bar_range   # 0.50
        close_pos = (102.0 - 96.0) / bar_range     # 0.75

        assert features["upper_wick_ratio"] == pytest.approx(upper_wick)
        assert features["lower_wick_ratio"] == pytest.approx(lower_wick)
        assert features["close_position_in_range"] == pytest.approx(close_pos)


class TestOrderFlowFeatures:
    """Group B: Order flow features."""

    def test_cvd_slope_and_aggression(self):
        """cvd_slope and aggression come from AMTResult."""
        data = _make_data(25)
        amt = _make_amt_result(cvd_slope=1.2, aggression=-0.5)
        tick = _make_ohlc()
        features = extract_features(data, amt, tick)

        assert features["cvd_slope"] == pytest.approx(1.2)
        assert features["aggression"] == pytest.approx(-0.5)

    def test_cvd_divergence_flag(self):
        """cvd_divergence_flag maps BULLISH_DIV->1, BEARISH_DIV->-1, else 0."""
        data = _make_data(25)
        tick = _make_ohlc()

        amt_bull = _make_amt_result(cvd_divergence="BULLISH_DIV")
        assert extract_features(data, amt_bull, tick)["cvd_divergence_flag"] == 1.0

        amt_bear = _make_amt_result(cvd_divergence="BEARISH_DIV")
        assert extract_features(data, amt_bear, tick)["cvd_divergence_flag"] == -1.0

        amt_none = _make_amt_result(cvd_divergence="")
        assert extract_features(data, amt_none, tick)["cvd_divergence_flag"] == 0.0

    def test_delta_normalized(self):
        """delta_normalized = delta / volume."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(volume=2000, delta=500)
        features = extract_features(data, amt, tick)

        assert features["delta_normalized"] == pytest.approx(500 / 2000)

    def test_delta_normalized_zero_volume(self):
        """delta_normalized defaults to 0 when volume is 0."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(volume=0, delta=500)
        features = extract_features(data, amt, tick)

        assert features["delta_normalized"] == 0.0


class TestVolumeProfileFeatures:
    """Group C: Volume profile structure features."""

    def test_profile_shape_encoded(self):
        """Profile shape encoding: P->1, b->-1, D->0."""
        data = _make_data(25)
        tick = _make_ohlc()

        amt_p = _make_amt_result(profile_shape="P")
        assert extract_features(data, amt_p, tick)["profile_shape_encoded"] == 1.0

        amt_b = _make_amt_result(profile_shape="b")
        assert extract_features(data, amt_b, tick)["profile_shape_encoded"] == -1.0

        amt_d = _make_amt_result(profile_shape="D")
        assert extract_features(data, amt_d, tick)["profile_shape_encoded"] == 0.0

    def test_market_state_encoded(self):
        """Market state encoding: IMBALANCED->1, BALANCED->0."""
        data = _make_data(25)
        tick = _make_ohlc()

        amt_imb = _make_amt_result(market_state="IMBALANCED")
        assert extract_features(data, amt_imb, tick)["market_state_encoded"] == 1.0

        amt_bal = _make_amt_result(market_state="BALANCED")
        assert extract_features(data, amt_bal, tick)["market_state_encoded"] == 0.0

    def test_nearest_lvn_distance(self):
        """nearest_lvn_distance_pct is distance to closest LVN / close."""
        data = _make_data(25)
        amt = _make_amt_result(lvns=(95.0, 110.0))
        tick = _make_ohlc(close=100.0)
        features = extract_features(data, amt, tick)

        # nearest LVN is 95.0, distance = |100 - 95| / 100 = 0.05
        assert features["nearest_lvn_distance_pct"] == pytest.approx(0.05)

    def test_empty_lvns_returns_zero(self):
        """When lvns is empty, nearest_lvn_distance_pct is 0.0."""
        data = _make_data(25)
        amt = _make_amt_result(lvns=())
        tick = _make_ohlc()
        features = extract_features(data, amt, tick)

        assert features["nearest_lvn_distance_pct"] == 0.0


class TestOrderBookFeatures:
    """Group D: Order book features."""

    def test_order_book_imbalance_and_spread(self):
        """Order book features computed when bids/asks are present."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc()
        ob = _make_order_book()
        features = extract_features(data, amt, tick, order_book=ob)

        assert features["bid_ask_spread_bps"] > 0
        assert -1.0 <= features["book_imbalance_l1"] <= 1.0
        assert -1.0 <= features["book_imbalance_l5"] <= 1.0
        assert features["bid_depth_total"] > 0
        assert features["ask_depth_total"] > 0

    def test_no_order_book_defaults(self):
        """Order book features default when order_book is None."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc()
        features = extract_features(data, amt, tick, order_book=None)

        assert features["bid_ask_spread_bps"] == 0.0
        assert features["book_imbalance_l1"] == 0.0
        assert features["book_imbalance_l5"] == 0.0
        assert features["bid_depth_total"] == 0.0
        assert features["ask_depth_total"] == 0.0
        assert features["book_pressure_ratio"] == 1.0

    def test_empty_order_book_defaults(self):
        """Order book features default when bids/asks are empty."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc()
        ob = OrderBook(bids=(), asks=())
        features = extract_features(data, amt, tick, order_book=ob)

        assert features["bid_ask_spread_bps"] == 0.0
        assert features["book_pressure_ratio"] == 1.0


class TestTemporalFeatures:
    """Group E: Temporal features."""

    def test_minutes_since_open_nse(self):
        """minutes_since_open for NSE (market opens at 09:15 IST)."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(time="2025-01-06T10:15:00")
        features = extract_features(data, amt, tick, is_mcx=False)

        # 10:15 - 09:15 = 60 minutes
        assert features["minutes_since_open"] == pytest.approx(60.0, abs=1.0)

    def test_session_flag_nse(self):
        """NSE session flags: 0=opening, 1=morning, 2=midday, 3=closing."""
        data = _make_data(25)
        amt = _make_amt_result()

        tick_opening = _make_ohlc(time="2025-01-06T09:30:00")
        assert extract_features(data, amt, tick_opening, is_mcx=False)["session_flag"] == 0.0

        tick_morning = _make_ohlc(time="2025-01-06T11:00:00")
        assert extract_features(data, amt, tick_morning, is_mcx=False)["session_flag"] == 1.0

    def test_day_of_week(self):
        """day_of_week returns weekday (0=Monday)."""
        data = _make_data(25)
        amt = _make_amt_result()
        # 2025-01-06 is a Monday
        tick = _make_ohlc(time="2025-01-06T10:00:00")
        features = extract_features(data, amt, tick)

        assert features["day_of_week"] == pytest.approx(0.0)


class TestEdgeCases:
    """Edge cases and defensive behaviour."""

    def test_insufficient_data_returns_defaults(self):
        """With few candles, ATR defaults gracefully."""
        data = [_make_ohlc()]  # only 1 bar
        amt = _make_amt_result()
        tick = _make_ohlc()
        features = extract_features(data, amt, tick)

        # Should not raise; atr_5 and atr_20 default to 0.0
        assert features["atr_5"] == 0.0
        assert features["atr_20"] == 0.0
        assert features["atr_ratio"] == 1.0  # default when atr_20 == 0

    def test_zero_volume_handling(self):
        """Zero volume doesn't cause division by zero."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(volume=0, delta=0)
        features = extract_features(data, amt, tick)

        assert features["delta_normalized"] == 0.0
        # tick volume is 0 but data has non-zero volumes, so 0/ema = 0.0
        assert features["volume_vs_ema20"] == 0.0

    def test_missing_amtresult_fields_default_to_zero(self):
        """AMTResult fields missing/None default to 0 via dataclass defaults."""
        data = _make_data(25)
        amt = AMTResult()  # all defaults
        tick = _make_ohlc(close=100.0)
        features = extract_features(data, amt, tick)

        # Key fields should be 0.0 with default AMTResult
        assert features["cvd_slope"] == 0.0
        assert features["aggression"] == 0.0
        assert features["balance_ratio"] == 0.0

    def test_doji_bar_closes_in_range(self):
        """Doji bar (open==close) with range=0 gets close_position_in_range=0.5."""
        data = _make_data(25)
        amt = _make_amt_result()
        tick = _make_ohlc(open=100.0, high=100.0, low=100.0, close=100.0)
        features = extract_features(data, amt, tick)

        assert features["body_pct"] == 0.0
        assert features["bar_range_pct"] == 0.0
        assert features["close_position_in_range"] == 0.5


class TestExtractFeaturesFromRow:
    """Test extract_features_from_row() for batch training."""

    def test_returns_42_features(self):
        """extract_features_from_row() returns all FEATURE_NAMES keys."""
        row = {
            "close": 100.0, "open": 99.5, "high": 101.0, "low": 99.0,
            "volume": 1000.0, "delta": 200.0,
            "poc": 100.0, "vah": 102.0, "val": 98.0,
            "session_vwap": 100.5,
            "cvd_slope": 0.5, "aggression": 0.3,
            "profile_shape": "D", "market_state": "BALANCED",
            "balance_ratio": 0.6,
            "timestamp": "2025-01-06 10:00:00",
        }
        features = extract_features_from_row(row)

        assert set(features.keys()) == set(FEATURE_NAMES)

    def test_all_values_are_floats(self):
        """All values from extract_features_from_row are floats."""
        row = {
            "close": 100.0, "open": 99.5, "high": 101.0, "low": 99.0,
            "volume": 1000.0, "delta": 200.0,
            "poc": 100.0, "vah": 102.0, "val": 98.0,
            "timestamp": "2025-01-06 10:00:00",
        }
        features = extract_features_from_row(row)

        for name, value in features.items():
            assert isinstance(value, float), f"{name} is {type(value)}"

    def test_zero_close_returns_all_zeros(self):
        """When close <= 0, all features are 0.0."""
        row = {"close": 0}
        features = extract_features_from_row(row)

        for name, value in features.items():
            assert value == 0.0

    def test_with_data_window(self):
        """Providing data_window enables proper ATR computation."""
        data = _make_data(25)
        row = {
            "close": 100.0, "open": 99.5, "high": 101.0, "low": 99.0,
            "volume": 1000.0, "delta": 200.0,
            "poc": 100.0, "vah": 102.0, "val": 98.0,
            "timestamp": "2025-01-06 10:00:00",
        }
        features = extract_features_from_row(row, data_window=data)

        # ATR should be computed from data_window (non-zero)
        assert features["atr_5"] > 0
        assert features["atr_20"] > 0


class TestActiveModelFeatures:
    """Test active_model_features() filtering."""

    def test_filters_to_schema_only(self):
        """active_model_features() returns only FEATURE_NAMES keys."""
        features = {name: 1.0 for name in FEATURE_NAMES}
        features["book_imbalance_l20"] = 0.5  # diagnostic-only
        features["extra_diagnostic"] = 99.0

        result = active_model_features(features)

        assert set(result.keys()) == set(FEATURE_NAMES)
        assert "book_imbalance_l20" not in result
        assert "extra_diagnostic" not in result

    def test_missing_features_default_to_zero(self):
        """Missing features default to 0.0."""
        result = active_model_features({})

        for name in FEATURE_NAMES:
            assert result[name] == 0.0
