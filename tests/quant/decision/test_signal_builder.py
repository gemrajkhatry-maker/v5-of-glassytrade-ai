import pytest
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import SignalBuilder
from quant.bars import Bar

def _ctx(**kw):
    bar = Bar(time="t", open=100.0, high=101.0, low=99.0, close=kw.get("close", 100.0), volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        poc=kw.get("poc", 100.0), vah=kw.get("vah", 102.0), val=kw.get("val", 98.0),
        leg_lvn=kw.get("leg_lvn", 0.0), tick_size=0.05,
        agent_direction=kw.get("direction", "LONG"), agent_probability=0.7,
    )

def _pass_results():
    return [GateResult(i, True) for i in range(1, 5)]

def test_build_returns_none_when_a_gate_fails():
    sb = SignalBuilder()
    results = _pass_results()
    results[3] = GateResult(4, False, "No direction")
    assert sb.build(_ctx(), results) is None

def test_build_returns_long_signal():
    sb = SignalBuilder()
    s = sb.build(_ctx(), _pass_results())
    assert s is not None and s.type == "LONG"
    # SL two ticks INSIDE VAL: val=98 -> 98.10
    assert s.sl == pytest.approx(98.0 + 0.10)
    assert s.sl < s.entry < s.tp
    assert s.rr >= 1.0

def test_build_tp_is_r_multiple():
    sb = SignalBuilder(tp_multiplier=2.0)
    s = sb.build(_ctx(), _pass_results())
    expected_tp = s.entry + (s.entry - s.sl) * 2.0
    assert s.tp == pytest.approx(expected_tp)

def test_model_label_populated():
    """Signal.model_label must be a non-empty string (replaces the removed confidence field)."""
    sb = SignalBuilder()
    s = sb.build(_ctx(), _pass_results(), model_label="Triple-A")
    assert s.model_label == "Triple-A"

def test_build_returns_none_when_sl_on_wrong_side_of_entry():
    sb = SignalBuilder()
    # entry 100 < val 110 so the anchor falls back to nearest_level=105;
    # SL = 105 - 0.10 = 104.90 lands above entry -> inverted -> rejected.
    ctx = _ctx(poc=100, vah=102, val=110)
    assert sb.build(ctx, _pass_results()) is None

def test_build_emits_short_with_sl_above_entry():
    sb = SignalBuilder()
    # SHORT: entry 100 < vah 102 -> SL = vah - 2 ticks = 101.90 (inside, above entry)
    ctx = _ctx(direction="SHORT", close=100.0, poc=98, vah=102, val=99)
    results = _pass_results()
    s = sb.build(ctx, results)
    assert s is not None and s.type == "SHORT"
    assert s.sl > s.entry > s.tp
    assert s.sl == pytest.approx(102.0 - 0.10)
