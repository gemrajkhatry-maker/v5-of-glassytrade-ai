# tests/quant/decision/test_squeeze_pullback.py
"""Gate 3 Fabio Playbook #4 — squeeze breakout pullback.

Previously these tests ran against phantom DecisionContext fields
(``squeeze_detected`` / ``absorption_cluster`` / ``pullback_confirmed``) that
were never populated, so they passed trivially. Task 2b replaced them with the
real detector output (``squeeze_direction`` / ``squeeze_trapped_level``) and
defined pullback concretely as a retest of the trapped VA level (within 3 ticks).
"""
import pytest

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def _base_ctx(direction="LONG", cvd_slope=0.3, close=100.0, squeeze_dir="LONG",
              trapped=100.0, tick_size=0.05, allow_trend=True) -> DecisionContext:
    bar = Bar(time="t", open=close, high=close + 0.2, low=close - 0.2,
              close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        agent_direction=direction,
        agent_probability=0.7,
        market_state="IMBALANCED",
        vwap_upper_2=110.0,
        vwap_lower_2=90.0,
        cvd_slope=cvd_slope,
        tick_size=tick_size,
        squeeze_detected=bool(squeeze_dir),
        squeeze_direction=squeeze_dir or "",
        squeeze_trapped_level=trapped,
        pullback_confirmed=abs(close - trapped) <= 3.0 * tick_size,
        allow_trend=allow_trend,
    )


def test_squeeze_long_pullback_passes_gate3():
    """LONG squeeze, bar retesting trapped level (2 ticks away) -> entry."""
    ctx = _base_ctx(direction="LONG", cvd_slope=0.3, close=100.10,
                    squeeze_dir="LONG", trapped=100.0)
    r = gate_triple_a_edge(ctx)
    assert r.passed and "Squeeze" in r.reason


def test_squeeze_short_pullback_passes_gate3():
    ctx = _base_ctx(direction="SHORT", cvd_slope=-0.3, close=99.90,
                    squeeze_dir="SHORT", trapped=100.0)
    r = gate_triple_a_edge(ctx)
    assert r.passed and "Squeeze" in r.reason


def test_squeeze_direction_mismatch_fails_gate3():
    """Squeeze signals LONG but agent is SHORT — no edge."""
    ctx = _base_ctx(direction="SHORT", cvd_slope=0.3, close=100.10,
                    squeeze_dir="LONG", trapped=100.0)
    r = gate_triple_a_edge(ctx)
    assert not r.passed


def test_squeeze_without_pullback_confirmation_fails_gate3():
    """Price far from the trapped level — no retest, no entry."""
    ctx = _base_ctx(direction="LONG", cvd_slope=0.3, close=102.0,
                    squeeze_dir="LONG", trapped=100.0)
    r = gate_triple_a_edge(ctx)
    assert not r.passed
    assert "No Triple-A edge" in r.reason


def test_squeeze_long_blocked_midday_without_trend():
    """Squeeze retest is a trend-continuation play: vetoed when the session
    is reversion-only (allow_trend=False) — mirrors the Initiative veto."""
    ctx = _base_ctx(direction="LONG", cvd_slope=0.0, close=100.10,
                    squeeze_dir="LONG", trapped=100.0, allow_trend=False)
    r = gate_triple_a_edge(ctx)
    assert not r.passed and "trend" in r.reason.lower()
