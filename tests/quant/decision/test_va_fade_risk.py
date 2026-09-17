# tests/quant/decision/test_va_fade_risk.py
"""Tests for Value-Area Fade Structural Risk and Invalidation (Task 5)."""

import pytest
from quant.decision.context import DecisionContext
from quant.decision.va_fade import detect_va_fade
from quant.bars import Bar


def _make_bar(c, l, h):
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=c,
        high=h,
        low=l,
        close=c,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
    )


def test_val_bounce_fade_has_structural_stop_below_probe_low():
    # probed below VAL, closed back inside VA
    bar = _make_bar(c=95.5, l=93.0, h=96.0)
    ctx = DecisionContext(
        bar=bar,
        poc=100.0,
        val=95.0,
        vah=105.0,
        tick_size=0.05,
        cvd_slope=1.0,
        session_extreme_low=93.0,
    )
    sig = detect_va_fade(ctx)
    assert sig is not None
    assert sig.direction == "LONG"
    assert sig.tp == 100.0
    assert sig.sl <= 93.0  # At or below probe low
    assert sig.entry == 95.5
    assert sig.rr > 0.0


def test_vah_rejection_fade_has_structural_stop_above_probe_high():
    # probed above VAH, closed back inside VA
    bar = _make_bar(c=104.5, l=104.0, h=107.0)
    ctx = DecisionContext(
        bar=bar,
        poc=100.0,
        val=95.0,
        vah=105.0,
        tick_size=0.05,
        cvd_slope=-1.0,
        session_extreme_high=107.0,
    )
    sig = detect_va_fade(ctx)
    assert sig is not None
    assert sig.direction == "SHORT"
    assert sig.tp == 100.0
    assert sig.sl >= 107.0  # At or above probe high
    assert sig.entry == 104.5
    assert sig.rr > 0.0


def test_inside_va_does_not_fade():
    bar = _make_bar(c=100.0, l=99.0, h=101.0)
    ctx = DecisionContext(
        bar=bar,
        poc=100.0,
        val=95.0,
        vah=105.0,
        tick_size=0.05,
        cvd_slope=1.0,
    )
    assert detect_va_fade(ctx) is None
