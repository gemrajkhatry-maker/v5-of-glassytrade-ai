from app.application.range_bar_builder import RangeBarBuilder


def _finalize_single_bar(builder):
    """Feed ticks through the public API to close exactly one range bar."""
    builder.on_tick(ltp=100.0, timestamp="t0", buy_vol=0.0, sell_vol=0.0)
    builder.on_tick(ltp=103.0, timestamp="t1", buy_vol=1000.0, sell_vol=0.0)
    return builder.on_tick(ltp=105.0, timestamp="t2", buy_vol=0.0, sell_vol=0.0)


def test_vp_volume_counted_once():
    b = RangeBarBuilder(range_size=5.0, tick_size=1.0)
    bar = _finalize_single_bar(b)
    assert bar is not None
    assert abs(bar.volume - 1000.0) < 1e-6
    assert abs(sum(b._vp_levels.values()) - 1000.0) < 1e-6


def test_vp_buy_sell_counted_once():
    b = RangeBarBuilder(range_size=5.0, tick_size=1.0)
    bar = _finalize_single_bar(b)
    assert abs(sum(b._vp_buy.values()) - 1000.0) < 1e-6
    assert abs(sum(b._vp_sell.values())) < 1e-6
