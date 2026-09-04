"""Contract tests for quantv2.orderflow.book — AMT §7 / fabio L96.

Doc-pinned numbers: OBI in [−1,1] as (bid−ask)/(bid+ask); wall = qty ≥ 3×
median level; stale > 10s; book truncated to 5 levels (Dhan reality).
"""
from quantv2.orderflow.book import DepthBook


def test_obi_walls_staleness():
    b = DepthBook(max_levels=5)
    b.apply_bid_ask([(100.0, 500), (99.95, 100)], [(100.05, 100), (100.10, 90)], ts=10.0)
    assert abs(b.obi() - (600 - 190) / 790) < 1e-9
    assert b.wall_levels(threshold_ratio=3.0)[0] and not b.wall_levels(threshold_ratio=3.0)[1]
    assert b.is_stale(25.0, max_age_s=10.0) is True and b.is_stale(15.0, max_age_s=10.0) is False
    assert abs(b.spread(0.05) - 0.05) < 1e-9


def test_obi_bounds():
    b = DepthBook(max_levels=5)
    assert b.obi() == 0.0
    b.apply_bid_ask([(100.0, 100)], [(100.05, 300)], ts=1.0)
    assert -1.0 <= b.obi() <= 1.0
    assert abs(b.obi() - (100 - 300) / 400) < 1e-9
    b.apply_bid_ask([(100.0, 100)], [], ts=2.0)
    assert abs(b.obi() - 1.0) < 1e-9


def test_max_levels_truncation():
    b = DepthBook(max_levels=5)
    bids = [(100.0 - 0.05 * i, 10) for i in range(8)]
    asks = [(100.05 + 0.05 * i, 10) for i in range(8)]
    b.apply_bid_ask(bids, asks, ts=0.0)
    assert len(b.bids) == 5 and len(b.asks) == 5
    assert b.best_bid == 100.0 and b.best_ask == 100.05


def test_best_bid_ask_none_when_empty():
    b = DepthBook(max_levels=5)
    assert b.best_bid is None and b.best_ask is None
    assert b.spread(0.05) is None


def test_one_sided_fraction():
    b = DepthBook(max_levels=5)
    assert b.one_sided_fraction(window_s=60) == 0.0
    b.add_print("BUY", ts=100.0)
    b.add_print("BUY", ts=110.0)
    b.add_print("SELL", ts=120.0)
    assert abs(b.one_sided_fraction(window_s=60) - 2 / 3) < 1e-9
    # now=120, window 10 → keeps BUY@110 and SELL@120 → 0.5


def test_one_sided_fraction_window_pruning():
    b = DepthBook(max_levels=5)
    b.add_print("BUY", ts=100.0)
    b.add_print("BUY", ts=100.0)
    b.add_print("SELL", ts=150.0)
    # window 60 → now=150, keeps ts>=90: all three → 2/3 dominant
    assert abs(b.one_sided_fraction(window_s=60) - 2 / 3) < 1e-9
    # window 10 → keeps only ts>=140: single SELL → fully one-sided
    assert abs(b.one_sided_fraction(window_s=10) - 1.0) < 1e-9


def test_stale_when_never_applied():
    b = DepthBook(max_levels=5)
    assert b.is_stale(100.0, max_age_s=10.0) is True
