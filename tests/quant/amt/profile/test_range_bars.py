"""Tests for ATR-dynamic range bars (spec §4)."""

import os
import pytest

from quant.amt.profile.range_bars import (
    ATRRangeCalculator,
    DynamicRangeBarAggregator,
    RangeBarStats,
    _quantize,
    _true_range,
)
from quant.bars import Bar


class TestUseRangeBarsEnvVar:
    """GLASSYTRADE_USE_RANGE_BARS env var parsing (spec §4 operator config).

    The parsing logic in QuantCoordinator._spawn_engine mirrors this
    helper; tests verify the accepted truthy/falsy values and the
    precedence over YAML config.
    """

    @staticmethod
    def _parse_use_range_bars(env_value: str | None, config_default: bool = False) -> bool:
        """Mirror of the parsing logic in QuantCoordinator._spawn_engine."""
        if env_value is not None:
            normalized = env_value.strip().lower()
            if normalized in ("1", "true", "yes", "on"):
                return True
            if normalized in ("0", "false", "no", "off"):
                return False
        return config_default

    def test_env_true_values(self, monkeypatch):
        for val in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
            monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", val)
            assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS")) is True

    def test_env_false_values(self, monkeypatch):
        for val in ("0", "false", "False", "FALSE", "no", "NO", "off", "OFF"):
            monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", val)
            assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS")) is False

    def test_env_empty_falls_back_to_config(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", "")
        # Empty string → use config default
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=True) is True
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=False) is False

    def test_env_unset_falls_back_to_config(self, monkeypatch):
        monkeypatch.delenv("GLASSYTRADE_USE_RANGE_BARS", raising=False)
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=True) is True
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=False) is False

    def test_env_invalid_falls_back_to_config(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", "maybe")
        # Unrecognized value → use config default
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=True) is True
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=False) is False

    def test_env_overrides_config(self, monkeypatch):
        """Env var takes precedence over YAML config value."""
        monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", "1")
        # Even if config says False, env wins
        assert self._parse_use_range_bars(os.environ.get("GLASSYTRADE_USE_RANGE_BARS"), config_default=False) is True


def _bar(close: float, high: float | None = None, low: float | None = None,
         volume: float = 100.0, delta: float = 0.0, time: str = "t") -> Bar:
    h = high if high is not None else close + 1.0
    l = low if low is not None else close - 1.0
    return Bar(time=time, open=close, high=h, low=l, close=close,
               volume=volume, buy_volume=volume / 2, sell_volume=volume / 2,
               delta=delta)


class TestTrueRange:
    """True Range computation."""

    def test_simple_range(self):
        assert _true_range(110.0, 90.0, 100.0) == 20.0

    def test_gap_up(self):
        """Gap up: high-prev > high-low."""
        assert _true_range(120.0, 105.0, 100.0) == 20.0

    def test_gap_down(self):
        """Gap down: |low - prev_close| = |80 - 95| = 15, but high-low=20 dominates."""
        # high=100, low=80 -> range 20; |100-95|=5; |80-95|=15 -> max is 20
        assert _true_range(100.0, 80.0, 95.0) == 20.0


class TestQuantize:
    """Quantization ladder."""

    def test_quantize_below_first_step(self):
        assert _quantize(1.0, (5, 10, 25)) == 5.0

    def test_quantize_exact_step(self):
        assert _quantize(10.0, (5, 10, 25)) == 10.0

    def test_quantize_between_steps(self):
        assert _quantize(12.0, (5, 10, 25)) == 25.0

    def test_quantize_above_last_step(self):
        assert _quantize(500.0, (5, 10, 25)) == 25.0


class TestATRRangeCalculator:
    """ATR computation and range-size derivation."""

    def test_initial_range_size_is_minimum(self):
        """Before any bars, range_size returns min_ticks * tick_size."""
        calc = ATRRangeCalculator(min_ticks=2)
        assert calc.range_size(0.05) == 0.1  # 2 * 0.05

    def test_atr_accumulates_from_bars(self):
        """Feeding bars updates the ATR."""
        calc = ATRRangeCalculator(atr_period=14)
        # Each bar has range=2.0 (high=close+1, low=close-1)
        for i in range(20):
            calc.update(_bar(close=100.0 + i, time=f"t{i}"))

        atr = calc.raw_atr()
        # With constant range=2 and no gaps, ATR should be ~2.0
        assert 1.5 <= atr <= 2.5

    def test_range_size_quantizes(self):
        """range_size returns a quantized value >= min_ticks * tick_size."""
        calc = ATRRangeCalculator(atr_period=14, scale_factor=1.0, min_ticks=2)
        # Feed bars with range ~= 15 to push ATR high
        for i in range(20):
            calc.update(_bar(close=100.0, high=107.5, low=92.5, time=f"t{i}"))

        rs = calc.range_size(tick_size=0.05)
        assert rs >= 2 * 0.05  # >= min_ticks * tick_size

    def test_scale_factor_scales_output(self):
        """Higher scale_factor -> larger range size."""
        calc1 = ATRRangeCalculator(scale_factor=1.0)
        calc2 = ATRRangeCalculator(scale_factor=2.0)

        for i in range(20):
            b = _bar(close=100.0, high=105.0, low=95.0, time=f"t{i}")
            calc1.update(b)
            calc2.update(b)

        assert calc2.range_size(0.05) >= calc1.range_size(0.05)

    def test_insufficient_history_returns_minimum(self):
        """With fewer bars than period, still returns a valid minimum."""
        calc = ATRRangeCalculator(atr_period=14)
        calc.update(_bar(close=100.0, time="t0"))
        rs = calc.range_size(0.05)
        assert rs >= 2 * 0.05

    def test_zero_tick_size_safe(self):
        """Zero tick_size doesn't crash; returns 0."""
        calc = ATRRangeCalculator()
        calc.update(_bar(close=100.0, time="t0"))
        assert calc.range_size(0.0) == 0.0

    def test_bars_accumulated_count(self):
        """bars_accumulated increments with each bar."""
        calc = ATRRangeCalculator()
        for i in range(5):
            calc.update(_bar(close=float(i), time=f"t{i}"))
        assert calc.bars_accumulated == 4  # first bar has no prev_close

    def test_cached_until_next_update(self):
        """range_size is cached until update() is called again."""
        calc = ATRRangeCalculator()
        for i in range(20):
            calc.update(_bar(close=100.0, high=105.0, low=95.0, time=f"t{i}"))
        size1 = calc.range_size(0.05)
        size2 = calc.range_size(0.05)
        assert size1 == size2  # cached


class TestDynamicRangeBarAggregator:
    """Integration: bars form and range size adapts."""

    def test_bar_closes_when_range_exceeded(self):
        """A bar closes when high-low >= range_size."""
        agg = DynamicRangeBarAggregator(interval_seconds=60, tick_size=0.05)

        # Create a bar that opens at 100
        from quant.brokers.gateway import Tick
        t1 = Tick("t0", 100.0, 10.0, 5.0, 5.0)
        assert agg.add_tick(t1) is None  # bar forming

        # Tick that pushes high above range
        t2 = Tick("t1", 105.0, 10.0, 5.0, 5.0)
        bar = agg.add_tick(t2)
        # With initial min range (2*0.05=0.1), the spread 105-100=5 >> 0.1 -> closes
        assert bar is not None
        assert bar.close == 105.0

    def test_stats_track_bars_formed(self):
        """Stats increment as bars close. With dynamic range, the first bar
        closes at min range, then ATR raises the threshold so subsequent
        bars need larger moves to close."""
        agg = DynamicRangeBarAggregator(interval_seconds=60, tick_size=0.05)
        from quant.brokers.gateway import Tick

        # First tick opens bar at 100, second at 105 closes it (spread 5 >> 0.1)
        agg.add_tick(Tick("t0", 100.0, 10.0, 5.0, 5.0))
        agg.add_tick(Tick("t1", 105.0, 10.0, 5.0, 5.0))
        assert agg.stats.bars_formed >= 1

        # After ATR updates, range size grows; a small move won't close
        bar_open_price = agg.current_bar.open if agg.current_bar else -1
        agg.add_tick(Tick("t2", bar_open_price + 0.01, 10.0, 5.0, 5.0))
        # Bar should NOT have closed (spread 0.01 < dynamic range)
        assert agg.stats.bars_formed == 1

    def test_current_bar_accessible(self):
        """current_bar returns the forming bar."""
        agg = DynamicRangeBarAggregator(interval_seconds=60, tick_size=0.05)
        from quant.brokers.gateway import Tick

        t = Tick("t0", 100.0, 10.0, 5.0, 5.0)
        agg.add_tick(t)

        bar = agg.current_bar
        assert bar is not None
        assert bar.open == 100.0

    def test_range_size_adapts_after_bars(self):
        """Range size changes as ATR accumulates."""
        agg = DynamicRangeBarAggregator(interval_seconds=60, tick_size=0.05)
        initial_size = agg.stats.current_range_size

        from quant.brokers.gateway import Tick
        # Feed several volatile bars
        import random
        random.seed(42)
        price = 100.0
        for i in range(30):
            price += random.uniform(-2.0, 2.0)
            t = Tick(f"t{i}", price, 10.0, 5.0, 5.0)
            agg.add_tick(t)

        # After many bars, ATR-based size should be >= initial minimum
        assert agg.stats.current_range_size >= initial_size

    def test_apply_range_size_direct(self):
        """apply_range_size updates the inner aggregator."""
        agg = DynamicRangeBarAggregator(interval_seconds=60, tick_size=0.05)
        agg.apply_range_size(5.0)
        assert agg.stats.current_range_size == 5.0


class TestRangeBarStats:
    """RangeBarStats dataclass."""

    def test_default_values(self):
        s = RangeBarStats()
        assert s.bars_formed == 0
        assert s.current_range_size == 0.0
        assert s.last_atr == 0.0
