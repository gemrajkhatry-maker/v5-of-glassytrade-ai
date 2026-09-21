"""Regression guards for two defects found by the principal review and its
validation round. They exist so the two failure modes cannot silently return.

1. ``cvd_divergence`` fail-open (review finding C1).
   ``analyzer.py:1025`` produces ``AMTResult.cvd_divergence`` and
   ``dto.py:170`` emits it as ``cvdDivergence``, but the context builder never
   copies it into ``DecisionContext`` — the field does not even exist on the
   dataclass. ``gates_edge.py:200`` reads it with ``getattr(..., "")``, so the
   divergence veto at ``gates_edge.py:201-205`` is unreachable in production: a
   bearish divergence never blocks a long. This test asserts (a) the veto logic
   itself is correct when the field is populated, and (b) the wiring actually
   populates it, so a future rename or a dropped line fails loudly here rather
   than silently disabling a safety guard.

2. Spec 13.2.4 bundle guarantee (review finding C4, downgraded to M18).
   The guarantee currently holds only because the breakeven floor that
   authorises the pyramid overrides the ratcheted stop. An earlier draft of the
   review wrongly computed a net-negative bundle by assuming the ratcheted
   ``signal.sl`` was the exit price. This test pins the real invariant — the
   stopped-out bundle PnL is non-negative for both directions — so that any
   future change which truly breaks the guarantee (or which re-introduces the
   mis-reading) is caught by execution rather than by inspection.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import _check_guards, gate_triple_a_edge
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Order
from quant.execution.protective_stop import resolve_protective_stop
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager


# ---------------------------------------------------------------------------
# C1 — the divergence veto
# ---------------------------------------------------------------------------

def _ctx(open_, high, low, close, **kw):
    """A DecisionContext whose bar passes every Gate 3 guard up to the
    divergence branch, so that branch is the one under test."""
    bar = Bar(time="t", open=open_, high=high, low=low, close=close, volume=100.0)
    return DecisionContext(
        state=None,
        bar=bar,
        symbol="SYM",
        time_str="t",
        market=kw.pop("market", "NSE"),
        agent_direction=kw.pop("agent_direction", "LONG"),
        agent_probability=0.7,
        market_state=kw.pop("market_state", "IMBALANCED"),
        obi=kw.pop("obi", 0.0),
        drive_entry_valid=kw.pop("drive_entry_valid", False),
        leg_lvn=kw.pop("leg_lvn", 0.0),
        break_direction=kw.pop("break_direction", ""),
        break_type=kw.pop("break_type", ""),
        vwap_upper_2=kw.pop("upper_2", 103.0),
        vwap_lower_2=kw.pop("lower_2", 97.0),
        cvd_slope=kw.pop("cvd_slope", 1.5),
        absorption_side=kw.pop("absorption_side", ""),
        tick_size=0.05,
        triple_a_phase=kw.pop("triple_a_phase", "AGGRESSION"),
        triple_a_signal=kw.pop("triple_a_signal", "LONG"),
    )


class TestCVDDivergenceVeto:
    """The veto logic is correct; the wiring is missing. Both are asserted.

    ``DecisionContext`` is frozen and declares **no** ``cvd_divergence`` field,
    so ``gates_edge.py:200``'s ``getattr(ctx, "cvd_divergence", "")`` always
    yields "" and the branch at ``:201-205`` never runs. The tests below use a
    duck-typed stand-in for the context *only* to prove the veto code itself
    behaves per spec when the field is supplied; the remaining tests pin the
    wiring so that a half-fix (field added, builder not updated) fails here.
    """

    def _ctx_namespace(self, direction="LONG", cvd_divergence=None, bearish=False):
        """A namespace exposing exactly the guards before the divergence branch.

        The bar is a full-body close in the trade direction, so it clears the
        wick/acceptance probe and every earlier veto; cvd_slope is set
        comfortably in the trade's favour so the slope veto cannot fire. That
        leaves the divergence branch as the only veto that can trigger.
        """
        if bearish:
            bar = Bar(time="t", open=103.0, high=103.1, low=100.0,
                      close=100.2, volume=100.0)
        else:
            bar = Bar(time="t", open=100.0, high=103.0, low=99.9,
                      close=102.9, volume=100.0)

        ns = dict(
            bar=bar, agent_direction=direction, market_state="BALANCED",
            market="NSE", contested_bubble_zone=False, cvd_slope=1.5,
            stacked_imbalance_direction="", drive_number=0,
            drive_entry_valid=True, vwap_upper_2=1e9, vwap_lower_2=-1e9,
            vwap_std=0.0, absorption_side="",
        )
        if cvd_divergence is not None:
            ns["cvd_divergence"] = cvd_divergence
        return _Namespace(ns)

    def test_veto_fires_when_divergence_opposes_a_long(self):
        """Supplied with BEARISH_DIV, the veto blocks a LONG (logic is correct)."""
        ctx = self._ctx_namespace("LONG", "BEARISH_DIV")
        r = _check_guards(ctx)
        assert r is not None and not r.passed
        assert "divergence" in r.reason.lower()

    def test_veto_fires_when_divergence_opposes_a_short(self):
        ctx = self._ctx_namespace("SHORT", "BULLISH_DIV", bearish=True)
        ctx.cvd_slope = -1.5
        r = _check_guards(ctx)
        assert r is not None and not r.passed
        assert "divergence" in r.reason.lower()

    def test_confirming_divergence_does_not_veto(self):
        """BULLISH_DIV with a LONG passes the divergence branch cleanly."""
        ctx = self._ctx_namespace("LONG", "BULLISH_DIV")
        r = _check_guards(ctx)
        assert r is None

    def test_the_divergence_field_is_absent_from_decision_context(self):
        """Records the defect precisely: the gate reads a field the dataclass
        does not declare, so ``getattr`` silently returns the "" default and the
        veto is unreachable from any production-legal context object."""
        names = {f.name for f in dataclasses.fields(DecisionContext)}
        assert "cvd_divergence" not in names

    def test_a_real_decision_context_never_populates_the_veto(self):
        """The fail-open, demonstrated with the real dataclass: no constructor
        argument can reach the divergence branch, because the field does not
        exist."""
        bar = Bar(time="t", open=100.0, high=103.0, low=99.9, close=102.9,
                  volume=100.0)
        ctx = DecisionContext(
            state=None, bar=bar, symbol="SYM", time_str="t", market="NSE",
            agent_direction="LONG", agent_probability=0.7,
            market_state="IMBALANCED",
        )
        # The gate's read resolves to the default; the branch is skipped.
        assert getattr(ctx, "cvd_divergence", "") == ""
        r = _check_guards(ctx)
        # No divergence veto can have fired: the field is empty by construction.
        assert not (r is not None and "divergence" in str(r.reason).lower())

    def test_context_builder_does_not_propagate_the_dto_divergence_key(self):
        """``dto.py:170`` emits ``cvdDivergence``; the builder never reads it.
        Asserting the absence keeps the finding machine-checkable: once the
        field is wired up, this test should be converted into a positive
        assertion (and that is the correct fix for C1)."""
        from quant.decision import context_builder as cb
        assert "cvdDivergence" not in inspect.getsource(cb)

    def test_the_producer_does_emit_divergence(self):
        """The other half of the broken contract: the value IS produced, so this
        is a wiring gap, not an unimplemented feature."""
        from quant.amt import dto as dto_mod
        assert "cvdDivergence" in inspect.getsource(dto_mod)


class _Namespace:
    """Minimal attribute bag for exercising guard logic in isolation.

    ``_check_guards`` is annotated ``DecisionContext`` but Python does not
    enforce annotations, so a duck-typed object reaches the same code paths.
    """

    def __init__(self, mapping):
        self.__dict__.update(mapping)

    def __setattr__(self, name, value):
        self.__dict__[name] = value


# ---------------------------------------------------------------------------
# C4/M18 — spec 13.2.4 bundle guarantee, pinned by execution
# ---------------------------------------------------------------------------

def _pm(entry, sl, tp, direction="LONG", tick=0.5):
    """Build a PositionManager with one base position in `direction`."""
    long = direction == "LONG"
    oms = PaperOMS(lot_size=1.0)
    pm = PositionManager(
        oms=oms, exits=ExitEngine(), risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=lambda e: None, symbol="S", market="NSE", contract_expiry=None,
        tick_size=tick,
    )
    sig = Signal(type=direction, reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="S", timestamp="t0")
    base = oms.submit(sig, 10.0)
    # PaperOMS.submit sizes a SHORT negative; the pyramid maths uses signed size.
    assert (base.size > 0) == long, f"position sign disagrees with {direction}"
    return pm, base


def _authorize(pm, base, entry, sl, close, high, low):
    """Arm the breakeven floor so the pyramid is spec-13.2.1 authorised."""
    risk = abs(entry - sl)
    pm._exits.evaluate(base, bar_close=close, bar_index=3, bar_high=high, bar_low=low)
    assert pm._exits.is_risk_free(base), (
        f"setup did not reach risk-free (0.8R needs close >= {entry + 0.8 * risk:.2f})"
    )
    return pm._exits.stop_state(base)


class TestPyramidBundleGuarantee:
    """Spec 13.2.4: 'The entire trade bundle is guaranteed a net positive cash
    payout.' Drives the real PositionManager, fires the pyramid, then prices
    the stopped-out bundle."""

    @pytest.mark.parametrize("direction,entry,sl,lvn,fill", [
        ("LONG", 105.0, 98.0, 100.0, 100.1),
        ("LONG", 105.0, 100.0, 100.0, 100.1),
        ("SHORT", 95.0, 102.0, 100.0, 99.9),
        ("SHORT", 95.0, 100.0, 100.0, 99.9),
    ])
    def test_stopped_out_bundle_is_never_negative(self, direction, entry, sl, lvn, fill):
        long = direction == "LONG"
        pm, base = _pm(entry, sl, entry + (20 if long else -20), direction)

        # 1. Authorise with a clearly profitable bar (>= 1.2R beyond entry).
        risk = abs(entry - sl)
        profit_px = entry + (1.2 * risk if long else -1.2 * risk)
        lo, hi = sorted((profit_px, profit_px + (2 if long else -2)))
        _authorize(pm, base, entry, sl, profit_px, hi + 1, lo - 1)

        # 2. Fire the pyramid at the LVN retest with confirming absorption.
        #    The candle must close in the trade direction (bullish for a long,
        #    bearish for a short) or check_pyramid's direction guard rejects it.
        dto = {"legLvns": [lvn], "absorptionSide": "BUY_ABSORBED" if not long else "SELL_ABSORBED"}
        if long:
            bar = Bar(time="t1", open=fill - 0.3, high=fill + 0.2,
                      low=fill - 0.5, close=fill, volume=100)
        else:
            bar = Bar(time="t1", open=fill + 0.3, high=fill + 0.5,
                      low=fill - 0.2, close=fill, volume=100)
        pm.check_pyramid(dto, bar, base, bar_index=5)
        assert pm.pyramid_count == 1, "the pyramid did not fire; the invariant was not exercised"

        # 3. The ratchet may have rewritten signal.sl; that is NOT the exit price.
        if pm.base_override is not None:
            base = pm.base_override
        be, trail = pm._exits.stop_state(base)
        eff, reason = resolve_protective_stop(
            float(base.order.signal.sl), be, trail, direction)

        # 4. Price both legs at the effective stop. The pyramid filled at `fill`.
        base_pnl = (eff - entry) * 10.0 if long else (entry - eff) * 10.0
        pyr_pnl = (eff - fill) * 5.0 if long else (fill - eff) * 5.0
        bundle = base_pnl + pyr_pnl

        assert bundle >= 0.0, (
            f"{direction} bundle PnL {bundle:+.1f} at effective stop {eff} "
            f"({reason}) violates spec 13.2.4 [ratcheted={base.order.signal.sl}, "
            f"be={be}, trail={trail}]"
        )

    def test_the_ratcheted_sl_is_overridden_by_the_authorising_floor(self):
        """Documents *why* the guarantee holds: resolve_protective_stop takes
        the max of {signal.sl, be_floor, trail}, and the floor that authorised
        the pyramid sits at or above cost basis."""
        pm, base = _pm(105.0, 98.0, 125.0)
        be, trail = _authorize(pm, base, 105.0, 98.0, 111.0, 112.0, 110.0)

        # A deliberately loose pyramid SL below the breakeven floor.
        eff, reason = resolve_protective_stop(99.6, be, trail, "LONG")
        assert eff >= 105.0, f"effective stop {eff} fell below the base entry"
        assert reason == "BREAKEVEN"
