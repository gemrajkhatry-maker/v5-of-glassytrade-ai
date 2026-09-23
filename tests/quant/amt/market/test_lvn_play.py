"""Unit tests for lvn_play_detector — LVN rejection plays."""


from quant.amt.market.lvn_play import detect_lvn_play
from quant.contracts.value_objects import OHLC


def _candle(o, h, lo, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=lo, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


class TestDetectLvnPlay:
    def test_no_lvns_returns_none(self):
        assert detect_lvn_play(_candle(100, 101, 99, 100), [], [], 100.0, 1000.0, 1.0) is None

    def test_zero_volume_returns_none(self):
        assert detect_lvn_play(_candle(100, 101, 99, 100, v=0), [100.0], [], 100.0, 1000.0, 1.0) is None

    def test_no_near_lvn_returns_none(self):
        assert detect_lvn_play(_candle(100, 101, 99, 100), [90.0], [], 100.0, 1000.0, 1.0) is None

    def test_velocity_plus_rejection_detects_play(self):
        # LVN at 100.0, price rejects lower prices (lower wick), volume spike
        candle = _candle(100.0, 100.4, 99.2, 100.3, v=3000, delta=200)
        result = detect_lvn_play(candle, [100.0], [], 100.0, 1000.0, 1.0)
        assert result is not None
        assert result["lvn_price"] == 100.0
        assert result["direction"] == "LONG"

    def test_target_uses_above_hvn(self):
        candle = _candle(100.0, 100.4, 99.2, 100.3, v=3000, delta=200)
        result = detect_lvn_play(candle, [100.0], [102.0, 103.0], 101.0, 1000.0, 1.0)
        assert result["target"] == 102.0

    def test_target_defaults_to_poc(self):
        candle = _candle(100.0, 100.4, 99.2, 100.3, v=3000, delta=200)
        result = detect_lvn_play(candle, [100.0], [], 101.0, 1000.0, 1.0)
        assert result["target"] == 101.0

    def test_insufficient_conditions_returns_none(self):
        # Only velocity, no rejection, no delta flip -> < 2 conditions
        candle = _candle(100.0, 101.0, 99.0, 100.5, v=3000, delta=0)
        result = detect_lvn_play(candle, [100.0], [], 101.0, 1000.0, 1.0)
        assert result is None

    def test_delta_flip_counts_as_condition(self):
        # velocity + delta flip (no rejection) = 2 conditions
        candle = _candle(100.0, 101.0, 99.0, 100.2, v=3000, delta=0)
        result = detect_lvn_play(candle, [100.0], [], 101.0, 1000.0,
                                 5.0, prev_cvd_slope=-5.0)
        assert result is not None
