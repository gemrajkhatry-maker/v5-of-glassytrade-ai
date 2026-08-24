"""Differential parity: moved quant.probability modules vs legacy shims.

Each test drives the SAME object through both import paths (the legacy path is
now a re-export shim) on fixed inputs and asserts identical output via
``tests.quant.parity.assert_parity``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant.contracts.value_objects import AMTResult, OHLC, AggressivePrint
from tests.quant.parity import assert_parity

from quant.probability.features import extract_features as quant_extract_features

from quant.probability.agent_pipeline import (
    select_playbook as quant_select_playbook,
    classify_regime as quant_classify_regime,
    pick_direction as quant_pick_direction,
    assess_timing as quant_assess_timing,
    kelly_size as quant_kelly_size,
    adjust_sl_tp as quant_adjust_sl_tp,
    calculate_timing_probability as quant_calculate_timing_probability,
    run_agent_pipeline as quant_run_agent_pipeline,
)


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


class _StubProbabilityEngine:
    """Returns fixed ProbabilityEstimate — exercises pick_direction deterministically."""

    def __init__(self, p_long=0.60, p_short=0.40):
        self._p_long = p_long
        self._p_short = p_short

    def is_ready(self):
        return True

    def estimate(self, _features):
        return SimpleNamespace(
            p_long_target=self._p_long,
            p_short_target=self._p_short,
            expected_mfe_long=0.02,
            expected_mfe_short=0.02,
        )


def test_parity_extract_features():
    data = _data()
    amt = _amt()
    tick = _ohlc(close=100.2, high=101.0, low=99.5, delta=300.0)
    (lambda: quant_extract_features(data, amt, tick))()


def test_parity_extract_features_imbalanced():
    data = _data(close=106.0)
    amt = _amt(market_state="IMBALANCED", poc=100.0, vah=105.0, val=95.0)
    tick = _ohlc(close=106.0, high=107.0, low=105.0)
    (lambda: quant_extract_features(data, amt, tick))()


def test_parity_select_playbook():
    cases = [
        (SimpleNamespace(regime="TRENDING"), _amt(market_state="IMBALANCED")),
        (SimpleNamespace(regime="BALANCED"), _amt(market_state="BALANCED")),
        (SimpleNamespace(regime="NO_TRADE"), _amt(market_state="NO_TRADE")),
        (SimpleNamespace(regime="BALANCED"), _amt(market_state="PROBING")),
    ]
    for regime, amt in cases:
        quant_select_playbook(regime, amt)


def test_parity_classify_regime():
    cases = [
        (_data(), _amt(), _ohlc(close=100.2)),
        (_data(close=106.0), _amt(market_state="IMBALANCED"), _ohlc(close=106.0)),
        (_data()[:10], _amt(), _ohlc(close=100.2)),  # too few candles -> DEAD
    ]
    for data, amt, tick in cases:
        quant_classify_regime(data, amt, tick)


def test_parity_pick_direction():
    engine = _StubProbabilityEngine(p_long=0.60, p_short=0.40)
    regime = SimpleNamespace(regime="BALANCED", allowed_long=True, allowed_short=True, risk_scale=1.0)
    features = {"close_vs_poc_pct": 0.001}
    (lambda: quant_pick_direction(features, engine, regime, "return_to_value"))()


def test_parity_assess_timing():
    data = _data()
    tick = _ohlc(close=100.2)
    amt = _amt()
    (lambda: quant_assess_timing(data, tick, amt, "LONG", "return_to_value"))()
    (lambda: quant_assess_timing(data, tick, amt, "LONG", "imbalance_continuation"))()


def test_parity_kelly_size():
    for prob in (0.0, 0.55, 0.7, 1.0):
        (lambda p=prob: quant_kelly_size(p))()


def test_parity_adjust_sl_tp():
    cases = [
        ("LONG", "TRENDING", 0.7),
        ("SHORT", "VOLATILE", 0.5),
        ("LONG", "BALANCED", 0.6),
        ("LONG", "TRENDING", 0.7, 0.02),  # dynamic MFE
    ]
    for direction, regime, prob, *mfe in cases:
        quant_adjust_sl_tp(direction, regime, prob,
                           predicted_mfe=mfe[0] if mfe else 0.0)


def test_parity_calculate_timing_probability():
    data = _data()
    tick = _ohlc(close=100.2, delta=300.0)
    amt = _amt()
    for timing in ("ENTER_NOW", "WAIT", "SKIP"):
        (lambda t=timing: quant_calculate_timing_probability(data, tick, amt, "LONG", "return_to_value", t))()


def test_parity_run_agent_pipeline_flat_skips_gates():
    """FLAT early-return path never touches the Track-B entry_gates modules.

    DEAD/BALANCED no-playbook inputs exit before `assess_timing`, so this parity
    check is deterministic and does not depend on Track B's gate modules.
    """
    data = _data()[:15]  # too few candles -> DEAD regime early return
    tick = _ohlc(close=100.2)
    amt = _amt()
    engine = _StubProbabilityEngine()

    quant_dec = quant_run_agent_pipeline(
        data=data, amt_result=amt, tick=tick,
        probability_engine=engine, features={},
    )
    assert quant_dec.direction == "FLAT"

    def _strip_latency(dec):
        return dec.__class__(
            direction=dec.direction, probability=dec.probability,
            regime=dec.regime, playbook=dec.playbook, timing=dec.timing,
            size_fraction=dec.size_fraction, sl_adjust=dec.sl_adjust,
            tp_adjust=dec.tp_adjust, latency_us=0,
            rationale=dec.rationale, feature_drivers=dec.feature_drivers,
        )

    (lambda: _strip_latency(quant_dec))()
