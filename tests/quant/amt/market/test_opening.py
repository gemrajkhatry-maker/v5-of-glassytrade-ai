"""Unit tests for OpeningTypeClassifier — market open auction analysis."""


from quant.amt.market.opening import OpeningTypeClassifier, OpeningTypeResult
from quant.contracts.value_objects import OHLC


def _candle(o, h, lo, c, v=1000) -> OHLC:
    return OHLC(time="09:15", open=o, high=h, low=lo, close=c, volume=v,
                delta=0.0, taker_buy_volume=0.0)


class TestOpeningTypeClassifier:
    def setup_method(self):
        self.cls = OpeningTypeClassifier(tick_size=0.05)

    def test_insufficient_data_returns_auction(self):
        result = self.cls.classify([], 100.0, 90.0, 95.0)
        assert result.type == "OPEN_AUCTION"
        assert result.confidence == 0.1

        result = self.cls.classify([_candle(100, 101, 99, 100)], 100.0, 90.0, 95.0)
        assert result.type == "OPEN_AUCTION"

    def test_open_drive_up(self):
        # First candle small, then strong upward move with close at top
        data = [
            _candle(100, 100.2, 99.8, 100.2),
            _candle(100.2, 101.5, 100.1, 101.3),
            _candle(101.3, 102.5, 101.2, 102.4),
        ]
        result = self.cls.classify(data, 100.0, 90.0, 95.0)
        assert result.type == "OPEN_DRIVE"

    def test_open_drive_down(self):
        data = [
            _candle(100, 100.2, 99.8, 99.8),
            _candle(99.8, 100.0, 98.6, 98.7),
            _candle(98.7, 98.8, 97.6, 97.7),
        ]
        result = self.cls.classify(data, 100.0, 90.0, 95.0)
        assert result.type == "OPEN_DRIVE"

    def test_quiet_open_is_auction(self):
        data = [
            _candle(100, 100.2, 99.8, 100.1),
            _candle(100.1, 100.3, 99.9, 100.0),
            _candle(100.0, 100.2, 99.8, 100.1),
        ]
        result = self.cls.classify(data, 100.0, 90.0, 95.0)
        assert result.type == "OPEN_AUCTION"

    def test_result_is_frozen_dataclass(self):
        result = self.cls.classify(
            [_candle(100, 100.5, 99.5, 100.2)], 100.0, 90.0, 95.0
        )
        assert isinstance(result, OpeningTypeResult)
        assert 0.0 <= result.confidence <= 1.0
        assert result.description
