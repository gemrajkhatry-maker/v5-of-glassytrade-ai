"""Tests for Task 4: Lee-Ready delta enable + volume spike clamp.

- Spike volume must be clamped to the contextual cap, not zeroed (audit P0-1).
- `set_delta_mode(True)` must switch the aggregator to Lee-Ready quote-rule
  classification instead of the body-ratio Gaussian proxy.
"""

from datetime import datetime

from app.application.candle_aggregator import CandleAggregator
from quant.contracts.timezones import IST

NOW = datetime(2026, 8, 6, 10, 0, 0, tzinfo=IST)


def test_volume_spike_clamped_not_zeroed():
    a = CandleAggregator(interval="5m")
    a.aggregate("SYM", NOW, 100.0, 1000, 0, 0, 0, best_bid=99, best_ask=101)

    # Cumulative volume jumps by 50000 in a single tick: way past the
    # contextual cap of max(10000, prev_cum_vol * 0.05) = 10000.
    out = a.aggregate("SYM", NOW, 100.0, 51000, 0, 0, 0, best_bid=99, best_ask=101)

    assert out is not None
    assert out.volume == 10000.0


def test_spike_cap_scales_with_cumulative_volume():
    a = CandleAggregator(interval="5m")
    a.aggregate("SYM", NOW, 100.0, 500000, 0, 0, 0, best_bid=99, best_ask=101)

    # cap = max(10000, 500000 * 0.05) = 25000
    out = a.aggregate("SYM", NOW, 100.0, 560000, 0, 0, 0, best_bid=99, best_ask=101)

    assert out is not None
    assert out.volume == 25000.0


def test_normal_volume_unaffected_by_clamp():
    a = CandleAggregator(interval="5m")
    a.aggregate("SYM", NOW, 100.0, 1000, 0, 0, 0, best_bid=99, best_ask=101)

    out = a.aggregate("SYM", NOW, 100.0, 1100, 0, 0, 0, best_bid=99, best_ask=101)

    assert out is not None
    assert out.volume == 100.0


def test_lee_ready_mode_uses_quote_rule_not_body_ratio():
    a = CandleAggregator(interval="5m")
    a.set_delta_mode(True)

    out = None
    for ltp, vol in [(100.0, 1000), (110.0, 2000), (90.0, 3000), (105.0, 4000)]:
        out = a.aggregate("SYM", NOW, ltp, vol, 0, 0, 0, best_bid=99, best_ask=101)

    # Candle: open=100 high=110 low=90 close=105 vol=3000.
    # Body-ratio proxy gives (5/20)*3000 = 750; Lee-Ready quote rule sees
    # close(105) >= ask(101) -> buyer-initiated, delta = +3000.
    assert out is not None
    assert out.delta == 3000.0


def test_body_ratio_proxy_default_when_lee_ready_off():
    a = CandleAggregator(interval="5m")

    out = None
    for ltp, vol in [(100.0, 1000), (110.0, 2000), (90.0, 3000), (105.0, 4000)]:
        out = a.aggregate("SYM", NOW, ltp, vol, 0, 0, 0, best_bid=99, best_ask=101)

    assert out is not None
    assert out.delta == 750.0
