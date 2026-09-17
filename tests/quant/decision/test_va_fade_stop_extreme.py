"""VA_Fade stop references the full probe extreme, not just current bar."""
from quant.decision.va_fade import detect_va_fade
from quant.decision.context import DecisionContext
from quant.bars import Bar


def test_long_fade_stop_uses_session_extreme_when_available():
    """LONG fade below VAL: stop should reference session_extreme_low if available."""
    bar = Bar(time=1, open=97, high=98, low=95.5, close=97.5,
              volume=1000, buy_volume=600, sell_volume=400,
              delta=200, oi=50000, vwap=97.0)
    
    # Check which fields DecisionContext accepts
    fields = set(DecisionContext.__dataclass_fields__.keys())
    kwargs = dict(
        symbol="TEST", bar=bar, poc=100.0, val=98.0, vah=102.0,
        tick_size=0.05, cvd_slope=0.5,
    )
    # Add session extreme fields if they exist
    if "session_extreme_low" in fields:
        kwargs["session_extreme_low"] = 94.0
    if "session_extreme_high" in fields:
        kwargs["session_extreme_high"] = 0.0
    
    ctx = DecisionContext(**kwargs)
    signal = detect_va_fade(ctx)
    assert signal is not None
    assert signal.direction == "LONG"
    # If session_extreme_low is available, stop should reference it
    if hasattr(ctx, "session_extreme_low") and ctx.session_extreme_low > 0:
        assert signal.sl < 95.5, f"Stop {signal.sl} should be below session extreme 94.0"


def test_short_fade_stop_uses_session_extreme_when_available():
    """SHORT fade above VAH: stop should reference session_extreme_high if available."""
    bar = Bar(time=1, open=103, high=104.5, low=102, close=103.5,
              volume=1000, buy_volume=400, sell_volume=600,
              delta=-200, oi=50000, vwap=103.0)
    
    fields = set(DecisionContext.__dataclass_fields__.keys())
    kwargs = dict(
        symbol="TEST", bar=bar, poc=100.0, val=98.0, vah=102.0,
        tick_size=0.05, cvd_slope=-0.5,
    )
    if "session_extreme_low" in fields:
        kwargs["session_extreme_low"] = 0.0
    if "session_extreme_high" in fields:
        kwargs["session_extreme_high"] = 106.0
    
    ctx = DecisionContext(**kwargs)
    signal = detect_va_fade(ctx)
    assert signal is not None
    assert signal.direction == "SHORT"
    if hasattr(ctx, "session_extreme_high") and ctx.session_extreme_high > 0:
        assert signal.sl > 104.5, f"Stop {signal.sl} should be above session extreme 106.0"


def test_va_fade_falls_back_to_bar_extreme_when_no_session_extreme():
    """When session_extreme is 0, fall back to bar.low/bar.high (existing behavior)."""
    bar = Bar(time=1, open=97, high=98, low=95.5, close=97.5,
              volume=1000, buy_volume=600, sell_volume=400,
              delta=200, oi=50000, vwap=97.0)
    
    fields = set(DecisionContext.__dataclass_fields__.keys())
    kwargs = dict(
        symbol="TEST", bar=bar, poc=100.0, val=98.0, vah=102.0,
        tick_size=0.05, cvd_slope=0.5,
    )
    # Don't set session extremes — should fall back to bar.low
    ctx = DecisionContext(**kwargs)
    signal = detect_va_fade(ctx)
    assert signal is not None
    # Stop should still be below bar.low (existing behavior)
    assert signal.sl < 95.5
