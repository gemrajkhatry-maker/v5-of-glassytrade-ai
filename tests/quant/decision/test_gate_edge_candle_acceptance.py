"""Gate 3 — 1-minute full-body candle close acceptance (Fabio Valentini).

Per the v6.0 decision specification, Gate 3 must reject entries taken on wicks
or mid-candle probes: "The 1-minute bar must close with a full body beyond the
structural breakout reference."

Before this rule, the setup paths approved on structure alone, so a signal that
fired early in a bar (or on a bar that had already rejected back through the
range) opened a position at an unfavourable price and put the structural stop
on the wrong side of the probe.

Operational definition used here:
  * the body must be at least ``_FULL_BODY_MIN_RATIO`` of the bar's range;
  * the close must sit in the outer ``1 - _CLOSE_NEAR_EXTREME_MIN`` of the bar
    in the trade direction (a close near the extreme, not mid-range);
  * a bar with no range is INDETERMINATE and must not block, because synthetic
    and halted-instrument bars legitimately have zero range and throwing on
    them would disable trading on thin contracts.
"""

from __future__ import annotations


from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def _ctx(open_, high, low, close, **kw):
    bar = Bar(time="t", open=open_, high=high, low=low, close=close, volume=100.0)
    direction = str(kw.pop("agent_direction", "LONG")).upper()
    return DecisionContext(
        state=None,
        bar=bar,
        symbol="SYM",
        time_str="t",
        market=kw.pop("market", "NSE"),
        agent_direction=direction,
        agent_probability=0.7,
        market_state=kw.pop("market_state", "IMBALANCED"),
        obi=kw.pop("obi", 0.0),
        drive_entry_valid=kw.pop("drive_entry_valid", False),
        leg_lvn=kw.pop("leg_lvn", 0.0),
        break_direction=kw.pop("break_direction", ""),
        break_type=kw.pop("break_type", ""),
        vwap_upper_2=kw.pop("upper_2", 103.0),
        vwap_lower_2=kw.pop("lower_2", 97.0),
        cvd_slope=kw.pop("cvd_slope", 1.5 if direction == "LONG" else -1.5),
        absorption_side=kw.pop(
            "absorption_side",
            "SELL_ABSORBED" if direction == "LONG" else "BUY_ABSORBED",
        ),
        session_vwap=kw.pop("session_vwap", 97.0 if direction == "LONG" else 100.5),
        absorption_cluster_high=kw.pop("absorption_cluster_high", 99.0 if direction == "LONG" else 100.2),
        absorption_cluster_low=kw.pop("absorption_cluster_low", 98.0 if direction == "LONG" else 100.1),
        tick_size=0.05,
        triple_a_phase=kw.pop("triple_a_phase", "AGGRESSION"),
        triple_a_signal=kw.pop("triple_a_signal", "LONG"),
    )


class TestLongAcceptance:
    def test_full_body_close_near_high_passes(self):
        """Body 2.9 of a 3.1 range, closing at the high end: a real acceptance."""
        result = gate_triple_a_edge(_ctx(100.0, 103.0, 99.9, 102.9, leg_lvn=102.9))
        assert result.passed

    def test_bearish_candle_is_rejected_for_a_long(self):
        result = gate_triple_a_edge(_ctx(101.0, 102.0, 99.0, 99.5))
        assert not result.passed
        assert "body" in result.reason.lower() or "down" in result.reason.lower()

    def test_mid_candle_probe_is_rejected(self):
        """Small body in the middle of the range: an early/probe entry."""
        result = gate_triple_a_edge(_ctx(100.0, 103.0, 99.0, 100.5))
        assert not result.passed

    def test_large_upper_wick_is_rejected(self):
        """Bullish close but the bar gave back almost all of its range."""
        result = gate_triple_a_edge(_ctx(100.0, 104.0, 99.9, 100.3))
        assert not result.passed


class TestShortAcceptance:
    def test_full_body_close_near_low_passes(self):
        result = gate_triple_a_edge(
            _ctx(101.0, 101.1, 98.0, 98.2, agent_direction="SHORT", triple_a_signal="SHORT", cvd_slope=-1.5, leg_lvn=98.2)
        )
        assert result.passed

    def test_bullish_candle_is_rejected_for_a_short(self):
        result = gate_triple_a_edge(
            _ctx(99.0, 101.0, 98.9, 100.5, agent_direction="SHORT", triple_a_signal="SHORT", cvd_slope=-1.5)
        )
        assert not result.passed

    def test_mid_candle_probe_is_rejected_for_a_short(self):
        result = gate_triple_a_edge(
            _ctx(100.0, 101.0, 97.0, 99.5, agent_direction="SHORT", triple_a_signal="SHORT", cvd_slope=-1.5)
        )
        assert not result.passed


class TestIndeterminateBarsDoNotBlock:
    def test_zero_range_bar_is_not_blocked_by_this_rule(self):
        """A flat bar cannot be judged; other guards still decide."""
        result = gate_triple_a_edge(_ctx(100.0, 100.0, 100.0, 100.0, leg_lvn=100.0))
        assert result.passed


class TestRuleAppliesToEveryStructuralPath:
    def test_drive_reclaim_entry_also_needs_acceptance(self):
        result = gate_triple_a_edge(
            _ctx(100.0, 103.0, 99.0, 100.5, drive_entry_valid=True, triple_a_phase="", triple_a_signal="")
        )
        assert not result.passed

    def test_initiative_breakout_entry_also_needs_acceptance(self):
        result = gate_triple_a_edge(
            _ctx(
                100.0,
                103.0,
                99.0,
                100.4,
                triple_a_phase="",
                triple_a_signal="",
                break_type="INITIATIVE",
                break_direction="UP",
            )
        )
        assert not result.passed

    def test_initiative_breakout_with_full_body_passes(self):
        result = gate_triple_a_edge(
            _ctx(
                100.0,
                103.0,
                99.9,
                102.9,
                triple_a_phase="",
                triple_a_signal="",
                break_type="INITIATIVE",
                break_direction="UP",
            )
        )
        assert result.passed
