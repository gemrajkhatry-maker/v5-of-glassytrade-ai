"""Gate 3 — TRIPLE_A_EDGE (Fabio: absorption -> accumulation -> aggression).

Simplified 2026-08-13: the edge exists in BOTH balanced and imbalanced
auctions (the playbook trades the same absorption/VWAP-breakout setup
everywhere); only a DEAD market rejects.
"""

import pytest

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.setup_state import SetupEvidence


def _ctx(**kw):
    close = kw.pop("close", 100.0)
    bar_vwap = kw.pop("bar_vwap", 0.0)
    bar = Bar(
        time="t", open=close, high=close, low=close, close=close,
        volume=100.0, vwap=bar_vwap,
    )
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
    absorption_side = kw.pop(
        "absorption_side",
        "BUY_ABSORBED" if agent_direction == "SHORT" else "SELL_ABSORBED",
    )
    triple_a_phase = kw.pop("triple_a_phase", "")
    triple_a_signal = kw.pop("triple_a_signal", "")
    setup_evidence = kw.pop("setup_evidence", None)
    compression_box_bars = kw.pop("compression_box_bars", 0)
    compression_box_vah = kw.pop("compression_box_vah", 0.0)
    compression_box_val = kw.pop("compression_box_val", 0.0)
    market = kw.pop("market", "NSE")
    session_vwap = kw.pop("session_vwap", 100.5 if agent_direction == "SHORT" else 99.0)
    cluster_high = kw.pop("absorption_cluster_high", 100.2 if agent_direction == "SHORT" else 99.9)
    cluster_low = kw.pop("absorption_cluster_low", 100.1 if agent_direction == "SHORT" else 99.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        market=market,
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
        session_vwap=session_vwap,
        absorption_cluster_high=cluster_high,
        absorption_cluster_low=cluster_low,
         tick_size=0.05,
         triple_a_phase=triple_a_phase,
         triple_a_signal=triple_a_signal,
         setup_evidence=setup_evidence,
         compression_box_bars=compression_box_bars,
         compression_box_vah=compression_box_vah,
         compression_box_val=compression_box_val,
     )


def test_passes_on_aggression_signal():

    r = gate_triple_a_edge(_ctx(triple_a_phase="AGGRESSION", triple_a_signal="LONG", cvd_slope=1.5, leg_lvn=100.0))
    assert r.passed and r.gate == 3


def test_partial_triple_a_evidence_cannot_bypass_gate3():
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        breakout_beyond_cluster=True,
        price=100.0,
        session_vwap=0.0,
    )
    result = gate_triple_a_edge(_ctx(setup_evidence=evidence))
    assert result.passed is False


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
    ctx = _ctx(
        agent_direction="SHORT",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
    )
    result = gate_triple_a_edge(ctx)
    assert not result.passed


def test_mcx_triple_a_requires_positive_long_cvd():
    adverse = gate_triple_a_edge(_ctx(
        market="MCX", agent_direction="LONG",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        cvd_slope=-0.40,
    ))
    assert not adverse.passed
    assert "CVD" in adverse.reason

    confirming = gate_triple_a_edge(_ctx(
        market="MCX", agent_direction="LONG",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        cvd_slope=0.40,
    ))
    assert confirming.passed


def test_mcx_triple_a_requires_negative_short_cvd():
    adverse = gate_triple_a_edge(_ctx(
        market="MCX", agent_direction="SHORT",
        triple_a_phase="AGGRESSION", triple_a_signal="SHORT",
        cvd_slope=0.40,
    ))
    assert not adverse.passed
    assert "CVD" in adverse.reason

    confirming = gate_triple_a_edge(_ctx(
        market="MCX", agent_direction="SHORT",
        triple_a_phase="AGGRESSION", triple_a_signal="SHORT",
        cvd_slope=-0.40,
    ))
    assert confirming.passed


def test_nse_triple_a_requires_positive_long_cvd():
    adverse = gate_triple_a_edge(_ctx(
        market="NSE", agent_direction="LONG",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        cvd_slope=-0.25,
    ))
    assert not adverse.passed
    assert "CVD" in adverse.reason

    confirming = gate_triple_a_edge(_ctx(
        market="NSE", agent_direction="LONG",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        cvd_slope=0.25,
    ))
    assert confirming.passed


def test_nse_triple_a_requires_negative_short_cvd():
    adverse = gate_triple_a_edge(_ctx(
        market="NSE", agent_direction="SHORT",
        triple_a_phase="AGGRESSION", triple_a_signal="SHORT",
        cvd_slope=0.25,
    ))
    assert not adverse.passed
    assert "CVD" in adverse.reason

    confirming = gate_triple_a_edge(_ctx(
        market="NSE", agent_direction="SHORT",
        triple_a_phase="AGGRESSION", triple_a_signal="SHORT",
        cvd_slope=-0.25,
    ))
    assert confirming.passed


@pytest.mark.parametrize("close", [0.0, -1.0])
def test_triple_a_rejects_nonpositive_close(close):
    result = gate_triple_a_edge(_ctx(
        agent_direction="SHORT",
        triple_a_phase="AGGRESSION",
        triple_a_signal="SHORT",
        close=close,
        cvd_slope=-1.0,
    ))
    assert result.passed is False


@pytest.mark.parametrize(
    "session_vwap",
    [0.0, -1.0, None, float("nan"), float("inf")],
)
def test_triple_a_does_not_fallback_to_bar_vwap(session_vwap):
    result = gate_triple_a_edge(_ctx(
        agent_direction="SHORT",
        triple_a_phase="AGGRESSION",
        triple_a_signal="SHORT",
        close=99.0,
        bar_vwap=100.0,
        session_vwap=session_vwap,
        cvd_slope=-1.0,
    ))
    assert result.passed is False


def test_complete_evidence_does_not_bypass_missing_session_vwap():
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        price_location="ABOVE_VAH",
        breakout_beyond_cluster=True,
        price=101.0,
        session_vwap=100.0,
        cluster_high=99.9,
        cluster_low=99.0,
        cvd_slope=1.0,
    )
    result = gate_triple_a_edge(_ctx(
        agent_direction="LONG",
        triple_a_phase="",
        triple_a_signal="",
        setup_evidence=evidence,
        close=101.0,
        bar_vwap=100.0,
        session_vwap=0.0,
        cvd_slope=1.0,
    ))
    assert result.passed is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"cvd_slope": None},
        {"cvd_slope": "bad"},
        {"close": None},
        {"close": "bad"},
        {"compression_box_bars": "bad"},
    ],
)
def test_direct_gate_fails_closed_for_malformed_numeric_inputs(overrides):
    kwargs = {
        "agent_direction": "SHORT",
        "triple_a_phase": "AGGRESSION",
        "triple_a_signal": "SHORT",
        "cvd_slope": -1.0,
    }
    kwargs.update(overrides)
    result = gate_triple_a_edge(_ctx(**kwargs))
    assert result.gate == 3
    assert result.passed is False

