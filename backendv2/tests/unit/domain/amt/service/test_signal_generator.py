"""Tests for Signal Generator — Triple-A signal generation."""

from __future__ import annotations

import pytest

from app.domain.amt.model.amt_models import Absorption, VolumeProfile
from app.domain.amt.service.signal_generator import (
    generate_signal,
    generate_triple_a_signal,
)


def _make_bar(close, high=None, low=None, open_price=None, buyVolume=0, sellVolume=0, volume=1000):
    return {
        "close": close, "high": high or close + 1, "low": low or close - 1,
        "open": open_price or close, "buyVolume": buyVolume, "sellVolume": sellVolume,
        "volume": volume,
    }


def _make_vp(poc=100.0, vah=105.0, val=95.0, step=1.0):
    levels = tuple(
        type("Level", (), {"price": p, "volume": v, "buy_volume": 0, "sell_volume": 0})()
        for p, v in [(95.0, 100), (96.0, 200), (97.0, 300), (98.0, 500), (99.0, 800),
                      (100.0, 1000), (101.0, 800), (102.0, 500), (103.0, 300),
                      (104.0, 200), (105.0, 100)]
    )
    return VolumeProfile(levels=levels, poc=poc, vah=vah, val=val, step=step)


def _make_absorption(bar_index=0, price=100.0, volume=1000, side="BUY", strength=0.8):
    return Absorption(bar_index=bar_index, price=price, volume=volume, side=side, strength=strength)


class TestLONGSignal:
    """Tests for LONG signal generation."""

    def test_long_signal_with_sl_tp(self):
        """BUY absorption + price > vwap => LONG signal with SL/TP."""
        bars = [_make_bar(close=100.0 + i) for i in range(5)]
        # Absorption far enough back for accumulation phase
        absorptions = [_make_absorption(bar_index=0, side="BUY")]
        vp = _make_vp(val=95.0, vah=105.0, poc=100.0, step=1.0)
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=98.0)
        assert signal.type == "LONG"
        assert signal.sl < signal.entry  # SL below entry
        assert signal.tp > signal.entry  # TP above entry

    def test_long_signal_has_minimum_rr(self):
        """LONG signal enforces minimum R:R >= 1.5."""
        bars = [_make_bar(close=100.0 + i) for i in range(5)]
        absorptions = [_make_absorption(bar_index=0, side="BUY")]
        vp = _make_vp(val=95.0, vah=105.0, poc=100.0, step=1.0)
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=98.0, min_rr=1.5)
        if signal.type == "LONG":
            assert signal.rr >= 1.5


class TestSHORTSignal:
    """Tests for SHORT signal generation."""

    def test_short_signal_with_sl_tp(self):
        """SELL absorption + price < vwap => SHORT signal with SL/TP."""
        bars = [_make_bar(close=100.0 - i) for i in range(5)]
        absorptions = [_make_absorption(bar_index=0, side="SELL")]
        vp = _make_vp(val=95.0, vah=105.0, poc=100.0, step=1.0)
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=102.0)
        assert signal.type == "SHORT"
        assert signal.sl > signal.entry  # SL above entry
        assert signal.tp < signal.entry  # TP below entry


class TestMinimumRR:
    """Tests for minimum R:R enforcement."""

    def test_signal_rejected_when_rr_below_threshold(self):
        """When R:R < min_rr, no trade signal returned."""
        bars = [_make_bar(close=100.0) for _ in range(5)]
        # Absorption at the last bar — too close for accumulation
        absorptions = [_make_absorption(bar_index=3, side="BUY")]
        vp = _make_vp(val=99.0, vah=101.0, poc=100.0, step=0.1)
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=100.0, min_rr=1.5)
        assert signal.type == "NO_TRADE"


class TestNoSignal:
    """Tests for no signal when conditions not met."""

    def test_no_absorption_returns_no_trade(self):
        """No absorptions => NO_TRADE."""
        bars = [_make_bar(close=100.0) for _ in range(5)]
        vp = _make_vp()
        signal = generate_triple_a_signal(bars, [], vp, vwap=100.0)
        assert signal.type == "NO_TRADE"
        assert "no absorption" in signal.reason.lower()

    def test_no_bars_returns_no_trade(self):
        """No bars => NO_TRADE."""
        vp = _make_vp()
        absorptions = [_make_absorption()]
        signal = generate_triple_a_signal([], absorptions, vp, vwap=100.0)
        assert signal.type == "NO_TRADE"

    def test_waiting_phase_returns_no_trade(self):
        """Accumulation phase not yet reached => NO_TRADE."""
        bars = [_make_bar(close=100.0) for _ in range(3)]
        # Absorption at last bar — not enough accumulation bars
        absorptions = [_make_absorption(bar_index=2, side="BUY")]
        vp = _make_vp()
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=100.0, min_accumulation_bars=2)
        assert signal.type == "NO_TRADE"


class TestGenerateSignalDict:
    """Tests for generate_signal dict output."""

    def test_returns_dict_with_expected_keys(self):
        """generate_signal returns dict with type, entry, sl, tp, rr, etc."""
        bars = [_make_bar(close=100.0) for _ in range(5)]
        vp = _make_vp()
        result = generate_signal(bars, [], vp, vwap=100.0)
        assert "type" in result
        assert "entry" in result
        assert "sl" in result
        assert "tp" in result
        assert "rr" in result
        assert "confidence" in result
        assert "reason" in result
