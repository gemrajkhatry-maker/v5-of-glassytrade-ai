"""Stage 3 contract: SessionKernel / auction-profile invariants."""

from __future__ import annotations

import pytest

from quant.amt.market.acceptance_rejection import AcceptanceRejectionEngine
from quant.amt.market.state_engine import detect_market_state
from quant.amt.orderflow.cvd import CVDTracker
from quant.amt.orderflow.drive import DriveTracker
from quant.amt.orderflow.footprint import FootprintAnalyzer
from quant.amt.profile.lvn import find_lvns
from quant.amt.profile.volume_profile import compute_value_area
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import OHLC, VolumeProfileLevel


def _candle(t: str, o: float, h: float, lo: float, c: float, v: float, delta: float = 0.0) -> OHLC:
    return OHLC.create(
        time=t, open=o, high=h, low=lo, close=c, volume=v, delta=delta,
        taker_buy_volume=max(0.0, (v + delta) / 2),
    )


def test_va_desert_covers_at_least_682():
    """Audit example: volumes 100,0,0,99 must still reach ≥68.2% coverage."""
    profile = [
        VolumeProfileLevel(price=100.0, volume=100.0),
        VolumeProfileLevel(price=101.0, volume=0.0),
        VolumeProfileLevel(price=102.0, volume=0.0),
        VolumeProfileLevel(price=103.0, volume=99.0),
    ]
    vah, val = compute_value_area(profile, poc_index=0, value_area_pct=0.682)
    covered = sum(p.volume for p in profile if val - 1e-9 <= p.price <= vah + 1e-9)
    total = sum(p.volume for p in profile)
    assert covered / total >= 0.682 - 1e-6


def test_lvn_clustering_keeps_stronger_trough():
    # Two adjacent troughs: strength of zero-vol > near-zero. Clustering must
    # keep the stronger (zero) trough.
    profile = [
        VolumeProfileLevel(price=100.0 + i, volume=v)
        for i, v in enumerate([80.0, 0.0, 0.5, 80.0])
    ]
    lvns = find_lvns(
        profile, min_separation=5.0, max_nodes=4, smoothing_window=1, lvn_percentile=100.0,
    )
    assert lvns
    best = max(lvns, key=lambda n: n.strength)
    assert best.price == pytest.approx(101.0)


def test_footprint_volume_conservation():
    from quant.contracts.value_objects import OHLC as VO
    # Build via FootprintAnalyzer with float fields (avoid Decimal*float).
    c = VO(
        time="2026-01-01T10:00:00+05:30",
        open=100.0, high=101.0, low=99.0, close=100.5,
        volume=100.0, delta=20.0, vwap=100.25,
        taker_buy_volume=60.0,
    )
    fp = FootprintAnalyzer()._generate_candle(c)
    buy = sum(int(lvl.ask) for lvl in fp.levels)
    sell = sum(int(lvl.bid) for lvl in fp.levels)
    assert buy + sell == round(float(c.volume))


def test_acceptance_sides_are_mutually_exclusive():
    eng = AcceptanceRejectionEngine(time_threshold=1.0, vol_ratio=0.0)
    above = _candle("2026-01-01T10:00:00+05:30", 110, 111, 109.5, 110.5, 100.0)
    r1 = eng.update(above, vah=100.0, val=90.0, baseline_vol=1.0)
    assert r1.acceptance_above is True
    below = _candle("2026-01-01T10:01:00+05:30", 80, 81, 79, 80.5, 100.0)
    r2 = eng.update(below, vah=100.0, val=90.0, baseline_vol=1.0)
    assert r2.acceptance_below is True
    assert r2.acceptance_above is False


def test_probe_rejection_inside_va_is_balanced():
    result = detect_market_state(
        price=105.0,
        poc=105.0,
        vah=110.0,
        val=100.0,
        tick_size=0.05,
        has_displacement=True,
        has_acceptance=False,
        balance_ratio=0.40,
        bar_high=111.0,
        bar_low=104.0,
    )
    assert result.state == MarketState.BALANCED


def test_cvd_seed_twenty_bars():
    tracker = CVDTracker()
    candles = [
        _candle(f"2026-01-01T10:{i:02d}:00+05:30", 100, 101, 99, 100.5, 100.0, delta=10.0)
        for i in range(20)
    ]
    for c in candles:
        tracker.update(c)
    assert tracker.value == pytest.approx(200.0)
    slope_via_state = tracker.state().slope
    # state() must not advance persistence relative to a second state() read
    assert tracker.state().slope == slope_via_state


def test_three_touches_without_departure_are_not_drive2():
    tracker = DriveTracker()
    level = 100.0
    for i in range(3):
        c = _candle(
            f"2026-01-01T10:{i * 5:02d}:00+05:30",
            100.0, 100.2, 99.8, 100.0, 50.0,
        )
        r = tracker.classify_touch(100.0, level, c, "LONG", tick_size=0.05)
        assert r.entry_valid is False
