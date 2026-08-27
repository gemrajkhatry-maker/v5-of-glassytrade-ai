# tests/quant/decision/test_squeeze_pullback.py
import pytest
from unittest.mock import MagicMock
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.context_builder import DecisionContext
from quant.contracts.enums import MarketState
from quant.bars import Bar


def _make_context(direction="LONG", squeeze=True, pullback=True, cvd_slope=0.1):
    ctx = MagicMock(spec=DecisionContext)
    ctx.contested_bubble_zone = False
    ctx.agent_direction = direction
    ctx.market_state = MarketState.IMBALANCED
    ctx.bar = Bar(time="t1", open=100.0, high=105.0, low=99.0, close=104.0, volume=100, buy_volume=60, sell_volume=40, delta=20, oi=1000, vwap=102.0)
    ctx.vwap_upper_2 = 110.0
    ctx.vwap_lower_2 = 90.0
    ctx.vwap_std = 1.0
    ctx.drive_number = 1
    ctx.drive_entry_valid = False
    ctx.cvd_slope = cvd_slope
    ctx.setup_evidence = None
    ctx.triple_a_phase = ""
    ctx.triple_a_signal = ""
    ctx.leg_lvn = 0.0
    ctx.break_direction = ""
    ctx.break_type = ""
    ctx.squeeze_detected = squeeze
    ctx.absorption_cluster = False
    ctx.pullback_confirmed = pullback
    return ctx


def test_squeeze_breakout_pullback_long_passes_gate_3():
    ctx = _make_context(direction="LONG", squeeze=True, pullback=True, cvd_slope=0.2)
    res = gate_triple_a_edge(ctx)
    assert res.passed is True
    assert "Squeeze breakout pullback LONG" in res.reason


def test_squeeze_breakout_pullback_short_passes_gate_3():
    ctx = _make_context(direction="SHORT", squeeze=True, pullback=True, cvd_slope=-0.2)
    res = gate_triple_a_edge(ctx)
    assert res.passed is True
    assert "Squeeze breakdown pullback SHORT" in res.reason


def test_squeeze_without_pullback_confirmation_fails_gate_3():
    ctx = _make_context(direction="LONG", squeeze=True, pullback=False, cvd_slope=0.2)
    res = gate_triple_a_edge(ctx)
    assert res.passed is False
    assert "No Triple-A edge" in res.reason
