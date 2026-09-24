"""P0-5 (gate layer) — Gate 3 must refuse a setup whose own flow evidence opposes.

``quant/amt/orderflow/compute.py`` marks ``cvd_confirmed`` True for either slope
sign and ``footprint_confirmed`` True on ``abs(norm_delta)``, so the aggregate
aggression score is direction-blind. Gate 3 is the decision authority and knows
``agent_direction``, so the directional consistency check belongs here.

Observed defect this pins down: the Triple-A AGGRESSION path returned True on
``triple_a_signal == agent_direction`` alone, so a setup whose absorption side
says the opposite (hidden seller absorbing buys while going LONG) still opened.
"""

from __future__ import annotations

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def _ctx(**kw):
    """Minimal Gate-3 context (mirrors tests/quant/decision/test_gate_triple_a_edge.py)."""
    close = kw.pop("close", 100.0)
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    agent_direction = kw.pop("agent_direction", "LONG")
    market_state = kw.pop("market_state", "IMBALANCED")
    cvd_slope = kw.pop("cvd_slope", 0.0)
    absorption_side = kw.pop(
        "absorption_side",
        "BUY_ABSORBED" if agent_direction == "SHORT" else "SELL_ABSORBED",
    )
    session_vwap = kw.pop("session_vwap", 100.5 if agent_direction == "SHORT" else 99.0)
    cluster_high = kw.pop("absorption_cluster_high", 100.2 if agent_direction == "SHORT" else 99.9)
    cluster_low = kw.pop("absorption_cluster_low", 100.1 if agent_direction == "SHORT" else 99.0)
    return DecisionContext(
        state=None,
        bar=bar,
        symbol="SYM",
        time_str="t",
        market=kw.pop("market", "NSE"),
        agent_direction=agent_direction,
        agent_probability=0.7,
        market_state=market_state,
        obi=kw.pop("obi", 0.0),
        drive_entry_valid=kw.pop("drive_entry_valid", False),
        leg_lvn=kw.pop("leg_lvn", close),
        break_direction=kw.pop("break_direction", ""),
        break_type=kw.pop("break_type", ""),
        vwap_upper_2=kw.pop("upper_2", 103.0),
        vwap_lower_2=kw.pop("lower_2", 97.0),
        cvd_slope=cvd_slope,
        absorption_side=absorption_side,
        session_vwap=session_vwap,
        absorption_cluster_high=cluster_high,
        absorption_cluster_low=cluster_low,
        tick_size=0.05,
        triple_a_phase=kw.pop("triple_a_phase", ""),
        triple_a_signal=kw.pop("triple_a_signal", ""),
    )


class TestOpposingAbsorptionBlocksEntry:
    """A setup is invalid when its absorption side contradicts the direction."""

    def test_long_blocked_when_buyers_are_absorbed(self):
        """BUY_ABSORBED = hidden seller = opposing evidence for a LONG."""
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                triple_a_phase="AGGRESSION",
                triple_a_signal="LONG",
                cvd_slope=1.5,
                absorption_side="BUY_ABSORBED",
            )
        )
        assert not result.passed
        assert "absorption" in result.reason.lower()

    def test_short_blocked_when_sellers_are_absorbed(self):
        """SELL_ABSORBED = hidden buyer = opposing evidence for a SHORT."""
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="SHORT",
                triple_a_phase="AGGRESSION",
                triple_a_signal="SHORT",
                cvd_slope=-1.5,
                absorption_side="SELL_ABSORBED",
            )
        )
        assert not result.passed
        assert "absorption" in result.reason.lower()

    def test_opposing_absorption_blocks_the_drive_path_too(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                drive_entry_valid=True,
                absorption_side="BUY_ABSORBED",
            )
        )
        assert not result.passed


class TestAgreeingAbsorptionAndFailClosedPaths:
    """Agreeing absorption passes; missing or unknown evidence fails closed."""

    def test_long_passes_with_agreeing_absorption(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                triple_a_phase="AGGRESSION",
                triple_a_signal="LONG",
                cvd_slope=1.5,
                absorption_side="SELL_ABSORBED",
            )
        )
        assert result.passed

    def test_short_passes_with_agreeing_absorption(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="SHORT",
                triple_a_phase="AGGRESSION",
                triple_a_signal="SHORT",
                cvd_slope=-1.5,
                absorption_side="BUY_ABSORBED",
            )
        )
        assert result.passed

    def test_aggression_path_rejects_missing_absorption(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                triple_a_phase="AGGRESSION",
                triple_a_signal="LONG",
                cvd_slope=1.5,
                absorption_side="",
            )
        )
        assert not result.passed
        assert "absorption" in result.reason.lower()

    def test_unknown_absorption_side_fails_closed(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                triple_a_phase="AGGRESSION",
                triple_a_signal="LONG",
                cvd_slope=1.5,
                absorption_side="NONE",
            )
        )
        assert not result.passed
        assert "absorption" in result.reason.lower()

    def test_evidence_free_aggression_rejects_missing_cluster(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                triple_a_phase="AGGRESSION",
                triple_a_signal="LONG",
                cvd_slope=1.5,
                absorption_side="SELL_ABSORBED",
                absorption_cluster_high=0.0,
                absorption_cluster_low=0.0,
            )
        )
        assert not result.passed
        assert "cluster" in result.reason.lower()

    def test_evidence_free_aggression_rejects_zero_cvd(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                triple_a_phase="AGGRESSION",
                triple_a_signal="LONG",
                cvd_slope=0.0,
                absorption_side="SELL_ABSORBED",
            )
        )
        assert not result.passed
        assert "cvd" in result.reason.lower()


class TestLvnSniperStillUsesCanonicalMapping:
    """The LVN Sniper path keeps its SELL_ABSORBED->LONG semantics."""

    def test_lvn_sniper_long_requires_sell_absorbed(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                leg_lvn=100.0,
                close=100.0,
                cvd_slope=0.5,
                absorption_side="SELL_ABSORBED",
            )
        )
        assert result.passed
        assert "LVN Sniper" in result.reason

    def test_lvn_sniper_long_rejected_with_buy_absorbed(self):
        result = gate_triple_a_edge(
            _ctx(
                agent_direction="LONG",
                leg_lvn=100.0,
                close=100.0,
                cvd_slope=0.5,
                absorption_side="BUY_ABSORBED",
            )
        )
        assert not result.passed
