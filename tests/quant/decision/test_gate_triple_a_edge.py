"""Gate 3 — TRIPLE_A_EDGE (Fabio: absorption -> accumulation -> aggression).

Simplified 2026-08-13: the edge exists in BOTH balanced and imbalanced
auctions (the playbook trades the same absorption/VWAP-breakout setup
everywhere); only a DEAD market rejects.
"""

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def _ctx(**kw):
    close = kw.pop("close", 100.0)
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    agent_direction = kw.pop("agent_direction", "LONG")
    market_state = kw.pop("market_state", "IMBALANCED")
    obi = kw.pop("obi", 0.0)
    drive_entry_valid = kw.pop("drive_entry_valid", False)
    leg_lvn = kw.pop("leg_lvn", 0.0)
    break_direction = kw.pop("break_direction", "")
    break_type = kw.pop("break_type", "")
    vwap_upper_2 = kw.pop("upper_2", 103.0)
    vwap_lower_2 = kw.pop("lower_2", 97.0)
    cvd_slope = kw.pop("cvd_slope", 0.0)
    absorption_side = kw.pop("absorption_side", "")
    triple_a_phase = kw.pop("triple_a_phase", "")
    triple_a_signal = kw.pop("triple_a_signal", "")
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        agent_direction=agent_direction,
        agent_probability=0.7,
        market_state=market_state,
        obi=obi,
        drive_entry_valid=drive_entry_valid,
        leg_lvn=leg_lvn,
        break_direction=break_direction,
        break_type=break_type,
        vwap_upper_2=vwap_upper_2,
        vwap_lower_2=vwap_lower_2,
        cvd_slope=cvd_slope,
        absorption_side=absorption_side,
        tick_size=0.05,
        triple_a_phase=triple_a_phase,
        triple_a_signal=triple_a_signal,
    )


def test_passes_on_aggression_signal():
    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION", triple_a_signal="LONG", cvd_slope=1.5))
    assert r.passed and r.gate == 3


def test_rejects_raw_absorption_without_accumulation_aggression():
    r = gate_triple_a_edge(_ctx(market_state="BALANCED", agent_direction="LONG", close=100.5))
    assert not r.passed
    assert "No Triple-A edge" in r.reason


def test_rejects_climax_overextension_long():
    """Price > VWAP +2.0σ is statistical exhaustion; reject climax top buying."""
    r = gate_triple_a_edge(_ctx(
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        close=104.0, upper_2=103.0, cvd_slope=1.0,
    ))
    assert not r.passed
    assert "climax" in r.reason.lower()


def test_rejects_climax_overextension_short():
    """Price < VWAP -2.0σ is statistical exhaustion; reject climax bottom selling."""
    r = gate_triple_a_edge(_ctx(
        agent_direction="SHORT",
        triple_a_phase="AGGRESSION", triple_a_signal="SHORT",
        close=96.0, lower_2=97.0, cvd_slope=-1.0,
    ))
    assert not r.passed
    assert "climax" in r.reason.lower()


def test_rejects_negative_cvd_slope_on_long():
    """Order flow pressure must agree: negative CVD slope blocks LONG entry."""
    r = gate_triple_a_edge(_ctx(
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        close=101.5, cvd_slope=-2.5,
    ))
    assert not r.passed
    assert "CVD slope aggressively negative" in r.reason


def test_rejects_positive_cvd_slope_on_short():
    """Order flow pressure must agree: positive CVD slope blocks SHORT entry."""
    r = gate_triple_a_edge(_ctx(
        agent_direction="SHORT",
        triple_a_phase="AGGRESSION", triple_a_signal="SHORT",
        close=98.5, cvd_slope=2.5,
    ))
    assert not r.passed
    assert "CVD slope aggressively positive" in r.reason


def test_passes_on_ib_second_drive_reclaim():
    """Path B: Second drive after failed auction is a valid institutional reclaim."""
    r = gate_triple_a_edge(_ctx(drive_entry_valid=True, cvd_slope=1.0))
    assert r.passed
    assert "Second Drive" in r.reason


def test_passes_on_impulse_leg_lvn_sniper():
    r = gate_triple_a_edge(_ctx(
        leg_lvn=100.0,
        close=100.05,
        absorption_side="SELL_ABSORBED",
        cvd_slope=1.0,
    ))
    assert r.passed
    assert "LVN Sniper" in r.reason


def test_rejects_dead_market():
    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION",
                                triple_a_signal="LONG", market_state="DEAD"))
    assert not r.passed
    assert "dead" in r.reason.lower()


def test_passes_on_initiative_breakout_long():
    """Path D: Initiative breakout in direction of break passes Gate 3."""
    r = gate_triple_a_edge(_ctx(
        agent_direction="LONG",
        break_direction="UP",
        break_type="INITIATIVE",
        cvd_slope=1.0,
    ))
    assert r.passed
    assert "Initiative upside breakout" in r.reason


def test_passes_on_initiative_breakdown_short():
    """Path D: Initiative breakdown in direction of break passes Gate 3."""
    r = gate_triple_a_edge(_ctx(
        agent_direction="SHORT",
        break_direction="DOWN",
        break_type="INITIATIVE",
        cvd_slope=-1.0,
    ))
    assert r.passed
    assert "Initiative downside breakdown" in r.reason


def test_fails_no_edge():
    r = gate_triple_a_edge(_ctx(market_state="BALANCED", agent_direction=None))
    assert not r.passed and r.gate == 3


def test_gate3_rejects_when_triple_a_signal_conflicts_with_agent_direction():
    from quant.decision.context_builder import DecisionContextBuilder
    from quant.decision.gates_edge import gate_triple_a_edge
    from quant.bars import Bar
    from quant.execution.risk import SessionRisk

    dto = {
        "absorptionSide": "BUY_ABSORBED",   # hierarchy -> agent_direction SHORT
        "tripleAPhase": "AGGRESSION",
        "tripleASignal": "LONG",            # evidence direction LONG
        "cvdSlope": 0.0,
        "marketState": "BALANCED",
    }
    ctx = DecisionContextBuilder().build(
        bar=Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0),
        symbol="S", market="NSE", contract_expiry=None, tick_size=0.05,
        bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=SessionRisk(storage=None, symbol="S").state(),
        amt_dto=dto,
    )
    assert ctx.agent_direction == "SHORT"
    assert ctx.setup_evidence is not None and ctx.setup_evidence.direction == "LONG"
    result = gate_triple_a_edge(ctx)
    assert not result.passed
    assert "conflicts" in result.reason
