"""Smoke coverage for the live quant.probability.features extraction path."""
from __future__ import annotations

from quant.contracts.value_objects import AMTResult, OHLC, AggressivePrint

from quant.probability.features import extract_features


def _ohlc(time="2026-01-01T10:00:00Z", close=100.0, high=None, low=None,
          open_=None, volume=1000.0, delta=200.0):
    return OHLC(
        time=time,
        open=open_ if open_ is not None else close,
        high=high if high is not None else close + 1.0,
        low=low if low is not None else close - 1.0,
        close=close,
        volume=volume,
        vwap=close,
        delta=delta,
    )


def _amt(market_state="BALANCED", poc=100.0, vah=105.0, val=95.0):
    return AMTResult(
        market_state=market_state,
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
        lvns=(95.5, 101.0),
        hvns=(98.0, 103.0),
        aggression=0.8,
        cvd_slope=0.6,
        cvd_divergence="",
        profile_shape="D",
        balance_ratio=0.6,
        session_vwap=100.0,
        aggressive_prints=(
            AggressivePrint(price=100.2, time="2026-01-01T10:00:00Z", side="BUY", volume=500, delta=250),
            AggressivePrint(price=100.1, time="2026-01-01T10:00:01Z", side="SELL", volume=200, delta=-100),
        ),
    )


def _data(n=25, close=100.0):
    return [_ohlc(time=f"2026-01-01T10:{i:02d}:00Z", close=close) for i in range(n)]


def test_extract_features():
    data = _data()
    amt = _amt()
    tick = _ohlc(close=100.2, high=101.0, low=99.5, delta=300.0)
    extract_features(data, amt, tick)


def test_extract_features_imbalanced():
    data = _data(close=106.0)
    amt = _amt(market_state="IMBALANCED", poc=100.0, vah=105.0, val=95.0)
    tick = _ohlc(close=106.0, high=107.0, low=105.0)
    extract_features(data, amt, tick)
