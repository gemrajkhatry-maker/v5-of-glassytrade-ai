"""Tests for compression box breakout confirmation in Triple-A AGGRESSION (spec §5.2 Layer 2).

When a compression box is detected (>= 3 bars), the Triple-A AGGRESSION path
requires the close to exceed the micro-VAH (LONG) or micro-VAL (SHORT).
A close inside the box is range rotation, not a breakout.
"""


from quant.amt.triple_a import AGGRESSION
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def _long_bar(close: float, time: str = "t") -> Bar:
    """A full-body bullish bar that passes candle acceptance.
    Body is 80% of range, close near the high (>= 75% of range)."""
    low = close - 0.5
    high = close + 2.0  # span = 2.5, body = close - open = 2.0
    open_px = close - 2.0  # body = 2.0, ratio = 2.0/2.5 = 0.8
    # (close - low) / span = (close - (close - 0.5)) / 2.5 = 0.5/2.5 = 0.2
    # That's not enough. Let me recalculate:
    # For close near high: (close - low) / span >= 0.75
    # close - low >= 0.75 * span
    # span = high - low. Let low = close - 0.5, high = close + 0.1
    # span = 0.6, close - low = 0.5, ratio = 0.5/0.6 = 0.83 ✓
    # body = close - open. For body_ratio >= 0.6: (close - open) / 0.6 >= 0.6
    # close - open >= 0.36. open <= close - 0.36
    low = close - 0.5
    high = close + 0.1
    open_px = close - 0.4  # body = 0.4, span = 0.6, ratio = 0.67 ✓
    return Bar(time=time, open=open_px, high=high, low=low, close=close,
               volume=1000.0, buy_volume=600.0, sell_volume=400.0)


def _short_bar(close: float, time: str = "t") -> Bar:
    """A full-body bearish bar that passes candle acceptance.
    Body is 80% of range, close near the low (>= 75% of range)."""
    # (high - close) / span >= 0.75
    high = close + 0.5
    low = close - 0.1
    open_px = close + 0.4  # body = -0.4, span = 0.6, ratio = 0.67 ✓
    return Bar(time=time, open=open_px, high=high, low=low, close=close,
               volume=1000.0, buy_volume=400.0, sell_volume=600.0)


def _bar(close: float, direction: str = "LONG", time: str = "t") -> Bar:
    """Create a bar in the given direction."""
    if direction == "SHORT":
        return _short_bar(close, time)
    return _long_bar(close, time)


def _ctx(**overrides) -> DecisionContext:
    """Build a minimal context for Triple-A AGGRESSION testing."""
    if "bar" not in overrides:
        overrides["bar"] = _long_bar(close=105.0)
    bar = overrides.pop("bar")
    fields = dict(
        bar=bar,
        symbol="NIFTY",
        agent_direction="LONG",
        triple_a_phase=AGGRESSION,
        triple_a_signal="LONG",
        leg_lvn=104.0,  # near the close for LVN proximity
        allow_trend=True,
        cvd_slope=0.5,
        market_state="IMBALANCED",
        tick_size=0.05,
    )
    fields.update(overrides)
    return DecisionContext(**fields)


class TestCompressionBoxBreakoutConfirmation:
    """Compression box breakout required for Triple-A AGGRESSION."""

    def test_passes_without_compression_box(self):
        """No compression box → standard LVN proximity gate applies."""
        ctx = _ctx(
            bar=_long_bar(close=105.0),
            compression_box_bars=0,
            compression_box_vah=0.0,
            compression_box_val=0.0,
            leg_lvn=104.9,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is True
        assert "AGGRESSION" in result.reason

    def test_passes_when_close_breaks_vah_long(self):
        """LONG close above compression box VAH → breakout confirmed."""
        ctx = _ctx(
            bar=_long_bar(close=105.0),
            compression_box_bars=5,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=104.9,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is True
        assert "AGGRESSION" in result.reason

    def test_blocked_when_close_inside_vah_long(self):
        """LONG close inside compression box VAH → blocked as range rotation."""
        ctx = _ctx(
            bar=_long_bar(close=101.0),  # below VAH at 102
            compression_box_bars=5,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=100.95,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is False
        assert "compression box VAH" in result.reason

    def test_passes_when_close_breaks_val_short(self):
        """SHORT close below compression box VAL → breakout confirmed."""
        ctx = _ctx(
            bar=_short_bar(close=97.0),
            agent_direction="SHORT",
            triple_a_signal="SHORT",
            compression_box_bars=5,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=97.05,  # within 5 ticks of close
            cvd_slope=-0.5,
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is True
        assert "AGGRESSION" in result.reason

    def test_blocked_when_close_inside_val_short(self):
        """SHORT close inside compression box VAL → blocked as range rotation."""
        ctx = _ctx(
            bar=_short_bar(close=99.0),  # above VAL at 98
            agent_direction="SHORT",
            triple_a_signal="SHORT",
            compression_box_bars=5,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=99.0,  # within 5 ticks of close
            cvd_slope=-0.5,
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is False
        assert "compression box VAL" in result.reason

    def test_box_too_small_ignored(self):
        """Compression box with < 3 bars → breakout check skipped."""
        ctx = _ctx(
            bar=_long_bar(close=101.0),  # inside VAH but box too small
            compression_box_bars=2,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=100.95,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is True  # box too small to enforce breakout

    def test_exact_threshold_enforces(self):
        """Compression box with exactly 3 bars enforces breakout."""
        ctx = _ctx(
            bar=_long_bar(close=101.5),  # inside VAH at 102
            compression_box_bars=3,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=101.45,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is False  # 3 bars triggers the check

    def test_close_exactly_at_vah_blocked(self):
        """Close exactly at VAH is NOT a breakout (must exceed)."""
        ctx = _ctx(
            bar=_long_bar(close=102.0),  # exactly at VAH
            compression_box_bars=5,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=101.95,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is False

    def test_close_just_above_vah_passes(self):
        """Close just above VAH (1 tick) is a valid breakout."""
        ctx = _ctx(
            bar=_long_bar(close=102.05),  # 1 tick above VAH
            compression_box_bars=5,
            compression_box_vah=102.0,
            compression_box_val=98.0,
            leg_lvn=102.0,  # within 5 ticks of close
        )
        result = gate_triple_a_edge(ctx)
        assert result.passed is True
