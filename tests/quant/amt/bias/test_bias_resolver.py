"""15-minute bias direction from bar structure and trend."""
import pytest
from quant.amt.bias.bias_resolver import BiasResolver, BiasDirection
from quant.bars import Bar


def _bar(ts, o, h, l, c, vol=1000):
    return Bar(time=ts, open=o, high=h, low=l, close=c,
               volume=vol, buy_volume=int(vol * 0.6),
               sell_volume=int(vol * 0.4), delta=int(vol * 0.2),
               oi=50000, vwap=(h + l + c) / 3)


class TestBiasResolver:
    def test_long_bias_on_higher_highs_and_higher_lows(self):
        bars = [
            _bar(1, 100, 102, 99, 101),
            _bar(2, 101, 103, 100, 102),
            _bar(3, 102, 105, 101, 104),
            _bar(4, 104, 106, 103, 105),
            _bar(5, 105, 107, 104, 106),
        ]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.LONG_BIAS
        assert result.confidence > 0.0

    def test_short_bias_on_lower_highs_and_lower_lows(self):
        bars = [
            _bar(1, 106, 107, 104, 105),
            _bar(2, 105, 106, 103, 104),
            _bar(3, 104, 105, 101, 102),
            _bar(4, 102, 103, 100, 101),
            _bar(5, 101, 102, 99, 100),
        ]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.SHORT_BIAS

    def test_neutral_on_mixed_structure(self):
        bars = [
            _bar(1, 100, 103, 98, 101),
            _bar(2, 101, 105, 96, 103),
            _bar(3, 103, 102, 99, 100),
            _bar(4, 100, 104, 97, 102),
            _bar(5, 102, 101, 100, 101),
        ]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.NEUTRAL

    def test_neutral_on_insufficient_data(self):
        bars = [_bar(1, 100, 102, 99, 101)]
        resolver = BiasResolver()
        result = resolver.resolve(bars)
        assert result.direction == BiasDirection.NEUTRAL
        assert result.confidence == 0.0

    def test_empty_bars_returns_neutral(self):
        resolver = BiasResolver()
        result = resolver.resolve([])
        assert result.direction == BiasDirection.NEUTRAL
        assert result.confidence == 0.0
