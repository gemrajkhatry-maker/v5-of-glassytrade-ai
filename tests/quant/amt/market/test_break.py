"""Unit tests for break_detector — initiative/responsive/absorption breaks."""


from quant.amt.market.break_detector import detect_break, check_ib_break_tick
from quant.contracts.value_objects import OHLC


def _candle(o, h, lo, c, v=1000, delta=0.0) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=lo, close=c, volume=v,
                delta=delta, taker_buy_volume=0.0)


class TestCheckIbBreakTick:
    def test_not_complete_returns_empty(self):
        result = check_ib_break_tick(105.0, 102.0, 98.0, False)
        assert result["break_direction"] == ""
        assert result["break_type"] == ""

    def test_invalid_ib_levels_returns_empty(self):
        result = check_ib_break_tick(105.0, 0.0, 0.0, True)
        assert result["break_direction"] == ""

    def test_break_up(self):
        result = check_ib_break_tick(103.0, 102.0, 98.0, True)
        assert result["break_direction"] == "UP"
        assert result["break_type"] == "INITIATIVE"
        assert result["break_level"] == 102.0
        assert result["break_price"] == 103.0

    def test_break_down(self):
        result = check_ib_break_tick(97.0, 102.0, 98.0, True)
        assert result["break_direction"] == "DOWN"
        assert result["break_type"] == "INITIATIVE"
        assert result["break_level"] == 98.0

    def test_inside_ib_returns_empty(self):
        result = check_ib_break_tick(100.0, 102.0, 98.0, True)
        assert result["break_direction"] == ""

    def test_reentry_clears_break_up(self):
        # Price back inside IB (100.0 between 98.0 and 102.0) clears break state
        result = check_ib_break_tick(100.0, 102.0, 98.0, True, current_break_direction="UP")
        assert result["break_direction"] == ""
        assert result["break_type"] == ""

    def test_reentry_clears_break_down(self):
        # Price back inside IB (100.0 between 98.0 and 102.0) clears break state
        result = check_ib_break_tick(100.0, 102.0, 98.0, True, current_break_direction="DOWN")
        assert result["break_direction"] == ""
        assert result["break_type"] == ""


class TestDetectBreak:
    def test_insufficient_data_returns_empty(self):
        assert detect_break([], 100.0, 90.0, 102.0, 98.0, 1000.0)["break_direction"] == ""
        assert detect_break(
            [_candle(100, 101, 99, 100)], 100.0, 90.0, 102.0, 98.0, 0
        )["break_direction"] == ""

    def test_initiative_break_up(self):
        data = [
            _candle(99, 100, 98, 99.5, 1000, 50),
            _candle(99.5, 100.5, 99, 100.0, 1000, 50),
            _candle(100.0, 101.0, 99.5, 100.8, 4000, 300),
        ]
        result = detect_break(data, vah=100.0, val=90.0, ib_high=0, ib_low=0,
                              baseline_vol=1000.0)
        assert result["break_direction"] == "UP"
        assert result["break_type"] == "INITIATIVE"
        assert result["break_level"] == 100.0

    def test_initiative_break_down(self):
        data = [
            _candle(101, 102, 100, 101.5, 1000, -50),
            _candle(101.5, 102, 100.5, 101.0, 1000, -50),
            _candle(101.0, 101.5, 99.2, 99.5, 4000, -300),
        ]
        result = detect_break(data, vah=100.0, val=100.0, ib_high=0, ib_low=0,
                              baseline_vol=1000.0)
        assert result["break_direction"] == "DOWN"
        assert result["break_type"] == "INITIATIVE"

    def test_no_break_without_volume(self):
        data = [
            _candle(99, 100, 98, 99.5, 1000, 50),
            _candle(99.5, 100.5, 99, 100.0, 1000, 50),
            _candle(100.0, 101.0, 99.5, 100.8, 1100, 300),
        ]
        result = detect_break(data, vah=100.0, val=90.0, ib_high=0, ib_low=0,
                              baseline_vol=1000.0)
        assert result["break_direction"] == ""

    def test_returns_break_result_keys(self):
        result = detect_break([], 100.0, 90.0, 102.0, 98.0, 1000.0)
        assert set(result) == {"break_direction", "break_type", "break_level",
                               "volume_ratio"}
