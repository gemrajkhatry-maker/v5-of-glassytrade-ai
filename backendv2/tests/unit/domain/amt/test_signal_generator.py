from app.domain.amt.model.amt_models import Absorption, VolumeProfile
from app.domain.amt.service.signal_generator import (
    ACCUMULATING,
    ABSORBING,
    WAITING,
    generate_triple_a_signal,
)


def test_waiting_phase_without_absorption_is_no_trade():
    signal = generate_triple_a_signal(
        bars=[],
        absorptions=[],
        vp=None,
        vwap=100.0,
    )

    assert signal.type == "NO_TRADE"
    assert WAITING in signal.reason


def test_absorbing_phase_blocks_signal_until_min_accumulation():
    bars = [
        {"high": 101.0, "low": 100.0, "close": 101.0, "volume": 100, "buyVolume": 55, "sellVolume": 45, "bar_index": 0},
        {"high": 102.0, "low": 100.5, "close": 102.0, "volume": 120, "buyVolume": 60, "sellVolume": 50, "bar_index": 1},
    ]
    absorptions = [Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)]
    vp = VolumeProfile(levels=(), poc=101.0, vah=102.0, val=100.0, step=1.0)

    signal = generate_triple_a_signal(
        bars=bars,
        absorptions=absorptions,
        vp=vp,
        vwap=102.0,
    )

    assert signal.type == "NO_TRADE"
    assert ABSORBING in signal.reason
    assert "need 1 accumulation bars" in signal.reason


def test_accumulating_phase_allows_primary_triple_a_signal():
    bars = [
        {"high": 101.0, "low": 100.0, "close": 101.0, "volume": 100, "buyVolume": 55, "sellVolume": 45, "bar_index": 0},
        {"high": 103.0, "low": 100.5, "close": 103.0, "volume": 120, "buyVolume": 60, "sellVolume": 50, "bar_index": 1},
        {"high": 105.0, "low": 102.0, "close": 105.0, "volume": 140, "buyVolume": 70, "sellVolume": 50, "bar_index": 2},
    ]
    absorptions = [Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)]
    vp = VolumeProfile(levels=(), poc=104.0, vah=105.0, val=100.0, step=1.0)

    signal = generate_triple_a_signal(
        bars=bars,
        absorptions=absorptions,
        vp=vp,
        vwap=100.0,
    )

    assert signal.type == "LONG"
    assert ACCUMULATING in signal.reason
    assert "Triple-A BUY absorption + R:R >= threshold (primary path)" in signal.reason


def test_va_fade_long_signal_is_selected_after_primary_filters_fail():
    bars = [
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 200, "buyVolume": 180, "sellVolume": 20, "bar_index": 0},
        {"high": 101.2, "low": 100.5, "close": 100.5, "volume": 140, "buyVolume": 90, "sellVolume": 50, "bar_index": 1},
        {"high": 101.0, "low": 99.5, "close": 100.2, "volume": 160, "buyVolume": 100, "sellVolume": 45, "bar_index": 2},
    ]
    absorptions = [Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)]
    vp = VolumeProfile(levels=(), poc=110.0, vah=103.0, val=100.0, step=1.0)

    signal = generate_triple_a_signal(
        bars=bars,
        absorptions=absorptions,
        vp=vp,
        vwap=101.0,
    )

    assert signal.type == "LONG"
    assert "VA-fade LONG at VAL with delta+VWAP; target POC" in signal.reason


def test_va_fade_short_signal_is_selected_after_primary_filters_fail():
    bars = [
        {"high": 105.0, "low": 103.0, "close": 104.0, "volume": 220, "buyVolume": 30, "sellVolume": 190, "bar_index": 0},
        {"high": 103.5, "low": 102.0, "close": 103.0, "volume": 170, "buyVolume": 70, "sellVolume": 100, "bar_index": 1},
        {"high": 102.5, "low": 101.0, "close": 102.0, "volume": 180, "buyVolume": 60, "sellVolume": 110, "bar_index": 2},
    ]
    absorptions = [Absorption(bar_index=0, price=104.0, volume=600.0, side="SELL", strength=0.83)]
    vp = VolumeProfile(levels=(), poc=96.0, vah=104.0, val=102.0, step=1.0)

    signal = generate_triple_a_signal(
        bars=bars,
        absorptions=absorptions,
        vp=vp,
        vwap=101.0,
    )

    assert signal.type == "SHORT"
    assert "VA-fade SHORT at VAH with delta+VWAP; target POC" in signal.reason
