"""Differential measurement: greenfield deterministic stack vs production AMT stack.

Feeds the canonical 60-bar session (``_session_bars`` from ``test_golden_file``)
and a signal-producing gentle-breakout session through BOTH gate paths and BOTH
exit paths, then compares per-bar pass/fail verdicts, blocking gates, resulting
signals, and exit decisions/reasons.

Run with ``-s`` to see the per-bar agreement tables:

    pytest tests/quant/consolidation/test_gate_divergence.py -q -s

The assertions below freeze the measured divergence facts so the harness doubles
as a regression guard for the KEEP-BOTH divergence budget documented in
``docs/GATE_CONSOLIDATION_REVIEW.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from quant.bars import Bar
from quant.coordinator import AuctionCoordinator
from quant.contracts.entities import Position as ProdPosition, Side
from quant.contracts.enums import MarketState as MS, SetupType, SignalType
from quant.contracts.value_objects import AMTResult, OHLC
from quant.decision.context import DecisionContext
from quant.decision.gates.gate_runner import run_gate_pipeline
from quant.decision.gates.legacy_gate_pipeline import (
    GateContext,
    GatePipeline as LegacyGatePipeline,
)
from quant.decision.gates.signal_builder import build_entry_signal
from quant.decision.pipeline import GatePipeline
from quant.decision.signal_builder import SignalBuilder
from quant.execution.exit_engine import ExitEngine as ProdExitEngine
from quant.execution.exits import ExitEngine as GreenfieldExitEngine
from quant.execution.order import Order, Position as GreenfieldPosition

from tests.quant.test_golden_file import _session_bars

TICK_SIZE = 0.05
SYMBOL = "SYNTH"
PROBABILITY = 0.7

REASON_TO_GATE = {
    "BLOCKED": 1,
    "STALE": 1,
    "SUPPRESSED": 1,
    "SESSION_STOPPED": 2,
    "FLAT": 2,
    "WAIT": 4,
    "INVALID": 5,
    "SKIP": 5,
}


def bar_to_ohlc(b: Bar) -> OHLC:
    return OHLC.create(
        b.time, b.open, b.high, b.low, b.close, b.volume, 0.0, b.buy_volume, b.delta
    )


def state_to_amt(state) -> AMTResult:
    vp, vwap, of = state.volume_profile, state.vwap, state.order_flow
    market_state = (
        "IMBALANCED"
        if state.triple_a_phase in ("AGGRESSION", "ACCUMULATING", "ABSORBING")
        else "BALANCED"
    )
    absorption_side = ""
    if state.absorption is not None:
        absorption_side = (
            "SELL_ABSORBED" if state.absorption.side == "BUY" else "BUY_ABSORBED"
        )
    return AMTResult(
        market_state=market_state,
        poc=vp.poc,
        value_area_high=vp.vah,
        value_area_low=vp.val,
        lvns=(),
        setup="imbalance_continuation" if market_state == "IMBALANCED" else "range_breakout",
        session_vwap=vwap.value,
        vwap_upper_1=vwap.upper_1,
        vwap_lower_1=vwap.lower_1,
        cvd_slope=of.cvd_slope,
        absorption_side=absorption_side,
        drive_number=0,
        drive_entry_valid=False,
        aggression=0.0,
    )


def _green_context(state, bar: Bar, agent_dir: str | None) -> DecisionContext:
    return DecisionContext(
        state=state,
        bar=bar,
        symbol=SYMBOL,
        agent_direction=agent_dir,
        agent_probability=PROBABILITY,
        session_open=True,
        warmup_complete=True,
        position_open=False,
        cooldown_remaining_sec=0,
        risk_halted=False,
    )


def green_verdict(state, bar: Bar, agent_dir: str | None):
    """Greenfield gate path: GatePipeline.evaluate + SignalBuilder.build.

    Returns (passed, failing_gate, signal_direction).
    """
    ctx = _green_context(state, bar, agent_dir)
    results = GatePipeline().evaluate(ctx)
    passed = all(r.passed for r in results)
    failing = next((r.gate for r in results if not r.passed), 0)
    signal_dir = None
    if passed:
        sig = SignalBuilder().build(ctx, results)
        signal_dir = ("LONG" if sig.is_buy else "SHORT") if sig is not None else None
    return passed, failing, signal_dir


def _prod_gate_context(data, amt: AMTResult, tick: OHLC, exec_dir, aggression) -> GateContext:
    """Mirror gate_runner.run_gate_pipeline's GateContext construction."""
    state_map = {
        "NO_TRADE": MS.BALANCED,
        "BALANCED": MS.BALANCED,
        "BALANCE": MS.BALANCED,
        "IMBALANCED": MS.IMBALANCED,
        "IMBALANCE": MS.IMBALANCED,
        "PROBING": MS.IMBALANCED,
    }
    ms = state_map.get(amt.market_state.upper(), MS.BALANCED)
    price = float(tick.close)
    levels = [amt.value_area_high, amt.value_area_low] + list(amt.lvns)
    valid = [lv for lv in levels if lv > 0]
    if valid:
        nearest = min(valid, key=lambda lv: abs(price - lv))
        dist_ticks = abs(price - nearest) / TICK_SIZE
    else:
        nearest, dist_ticks = price, 0.0
    risk = (
        abs(price - amt.value_area_low)
        if price > amt.poc
        else abs(amt.value_area_high - price)
    )
    reward = abs(amt.poc - price)
    rr = reward / risk if risk > 0 else 0.0
    absorption_detected = bool(getattr(amt, "absorption_side", "") or "")
    cvd_conflict = (exec_dir == "LONG" and amt.cvd_slope < 0) or (
        exec_dir == "SHORT" and amt.cvd_slope > 0
    )
    return GateContext(
        symbol=SYMBOL,
        candle_count=len(data),
        tick_age_seconds=1.0,
        market_state=ms,
        poc=amt.poc,
        vah=amt.value_area_high,
        val=amt.value_area_low,
        price=price,
        tick_size=TICK_SIZE,
        nearest_level=nearest,
        distance_to_level_ticks=dist_ticks,
        drive_number=0,
        drive_entry_valid=False,
        aggression_score=aggression,
        cvd_conflict=cvd_conflict,
        is_risk_halted=False,
        halt_reason="",
        eia_window_active=False,
        weekly_bias="NEUTRAL",
        weekly_bias_aligned=True,
        is_extreme_deviation=False,
        setup_type=amt.setup or "NONE",
        r_r_ratio=rr,
        cushion_ticks=dist_ticks,
        max_distance_to_level_ticks=3.0,
        probing_aggression_threshold=2.0,
        min_aggression_score=2.0,
        max_cushion_ticks=10.0,
        min_rr_ratio=1.5,
        absorption_detected=absorption_detected,
        absorption_bar_age=0,
        vwap_breakout=None,
    )


def production_verdict(data, amt: AMTResult, tick: OHLC, exec_dir, aggression):
    """Production gate path: gate_runner entry point + legacy GatePipeline.

    Returns (passed, failing_gate, reason, detail). The gate number comes from a
    mirror GateContext; its reason is cross-checked against run_gate_pipeline so
    the mirror cannot drift from the real entry point.
    """
    result = LegacyGatePipeline().evaluate(
        _prod_gate_context(data, amt, tick, exec_dir, aggression)
    )
    _, reason, detail, _, _ = run_gate_pipeline(
        data=data,
        amt_result=amt,
        tick=tick,
        market_state=amt.market_state,
        drive_number=0,
        drive_entry_valid=False,
        aggression_score=aggression,
        cvd_conflict=(
            exec_dir == "LONG" and amt.cvd_slope < 0
        ) or (exec_dir == "SHORT" and amt.cvd_slope > 0),
        is_risk_halted=False,
        halt_reason="",
        tick_age_seconds=1.0,
        symbol=SYMBOL,
        max_distance_to_level_ticks=3.0,
        probing_aggression_threshold=2.0,
        min_aggression_score=2.0,
        max_cushion_ticks=10.0,
        min_rr_ratio=1.5,
        tick_size=TICK_SIZE,
    )
    assert reason == result.reason.value, f"mirror drift: {reason} != {result.reason.value}"
    failing = 0 if result.passed else result.gate
    return result.passed, failing, result.reason.value, result.detail


def run_gate_differential(bars):
    """Run both gate paths over every bar; return per-bar verdict rows."""
    coord = AuctionCoordinator()
    ohcls = []
    rows = []
    for i, b in enumerate(bars):
        state = coord.on_bar_close(b)
        ohlc = bar_to_ohlc(b)
        ohcls.append(ohlc)
        agent_dir = state.triple_a_signal
        g_passed, g_fail, g_dir = green_verdict(state, b, agent_dir)
        amt = state_to_amt(state)
        p_passed, p_fail, p_reason, p_detail = production_verdict(
            ohcls, amt, ohlc, agent_dir, aggression=0.0
        )
        rows.append(
            {
                "i": i,
                "phase": state.triple_a_phase,
                "dir": agent_dir,
                "close": state.close,
                "g_passed": g_passed,
                "g_fail": g_fail,
                "g_dir": g_dir,
                "p_passed": p_passed,
                "p_fail": p_fail,
                "p_reason": p_reason,
                "p_detail": p_detail,
            }
        )
    return rows


def _print_gate_table(label, rows):
    agree = sum(1 for r in rows if r["g_passed"] == r["p_passed"])
    gate_agree = sum(
        1
        for r in rows
        if not r["g_passed"] and not r["p_passed"] and r["g_fail"] == r["p_fail"]
    )
    print(f"\n=== {label}: pass/fail agreement {agree}/{len(rows)} "
          f"({agree / len(rows) * 100:.1f}%) | same-blocking-gate {gate_agree}/{len(rows)}")
    for r in rows:
        if r["phase"] != "WAITING" or r["g_passed"] or r["p_passed"]:
            print(
                f"  bar {r['i']:2d} {r['phase']:12s} dir={str(r['dir']):5s} "
                f"green=pass:{r['g_passed']} g{r['g_fail']} sig={str(r['g_dir']):5s} | "
                f"prod=pass:{r['p_passed']} g{r['p_fail']} {r['p_reason']:8s} {r['p_detail']}"
            )
    return agree, gate_agree


def test_golden_session_gate_verdict_agreement():
    """Canonical 60-bar session: both stacks reject every bar, never the same gate.

    Greenfield blocks on gate 3 (58 bars: no agent direction) and gate 5 (2 bars:
    AGGRESSION breakout stop exceeds the 20-tick budget). Production blocks on
    gate 1 (warm-up), gate 4 (price > 3 ticks from a VA boundary — 50 bars) and
    gate 2 (PROBING without high aggression — the 8 imbalance bars). No bar shares
    the same blocking gate, so the stacks can never co-fire.
    """
    rows = run_gate_differential(_session_bars())
    agree, gate_agree = _print_gate_table("golden _session_bars (n=60)", rows)

    assert agree == 60
    assert gate_agree == 0

    green_fails = sorted(r["g_fail"] for r in rows)
    prod_fails = sorted(r["p_fail"] for r in rows)
    assert green_fails == [3] * 58 + [5] * 2
    assert prod_fails == [1] * 2 + [2] * 8 + [4] * 50

    aggression = [r for r in rows if r["phase"] == "AGGRESSION"]
    assert len(aggression) == 2
    for r in aggression:
        assert r["g_fail"] == 5
        assert r["p_fail"] == 2

    assert all(not r["g_passed"] and not r["p_passed"] for r in rows)


def _gentle_session() -> list[Bar]:
    out = [
        Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100)
        for i in range(25)
    ]
    out.append(
        Bar(time="t25", open=100, high=100, low=100, close=100,
            volume=500, buy_volume=450, sell_volume=50, delta=400)
    )
    for i in range(26, 28):
        out.append(
            Bar(time=f"t{i}", open=100, high=100, low=100, close=100,
                volume=100, buy_volume=60, sell_volume=40)
        )
    for i in range(28, 32):
        close = 100.3 + (i - 28) * 0.1
        out.append(
            Bar(time=f"t{i}", open=close - 0.2, high=close + 0.2,
                low=close - 0.2, close=close, volume=100)
        )
    for i in range(32, 60):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    return out


def test_gentle_session_signal_divergence():
    """Gentle breakout: greenfield PASSES all 5 gates and emits LONG on the
    AGGRESSION bar; production rejects that same bar (gate 2 with the greenfield-
    derived aggression=0, or gate 4 at 9.2 ticks from level once aggression is
    supplied). The only divergence is exactly that one bar.
    """
    rows = run_gate_differential(_gentle_session())
    agree, gate_agree = _print_gate_table("gentle breakout (n=60)", rows)

    assert agree == 59
    assert gate_agree == 0

    fired = [r for r in rows if r["g_passed"]]
    assert len(fired) == 1
    r = fired[0]
    assert r["i"] == 28
    assert r["phase"] == "AGGRESSION"
    assert r["g_dir"] == "LONG"
    assert not r["p_passed"]
    assert r["p_fail"] == 2

    bars = _gentle_session()
    coord = AuctionCoordinator()
    for b in bars[:28]:
        coord.on_bar_close(b)
    state28 = coord.on_bar_close(bars[28])
    data = [bar_to_ohlc(b) for b in bars[:29]]
    ohlc = bar_to_ohlc(bars[28])
    amt = state_to_amt(state28)
    with_aggression = production_verdict(data, amt, ohlc, "LONG", aggression=3.0)
    assert not with_aggression[0]
    assert with_aggression[1] == 4


def _find_green_signal(bars):
    coord = AuctionCoordinator()
    pipe = GatePipeline()
    sb = SignalBuilder()
    for i, b in enumerate(bars):
        state = coord.on_bar_close(b)
        if state.triple_a_phase == "AGGRESSION" and state.triple_a_signal == "LONG":
            ctx = _green_context(state, b, "LONG")
            results = pipe.evaluate(ctx)
            if all(r.passed for r in results):
                sig = sb.build(ctx, results)
                if sig is not None:
                    return state, b, sig
    return None, None, None


def test_signal_sltp_geometry_divergence():
    """On the same entry the two signal builders produce very different stops:
    greenfield sizes a structural stop one VP-step below the anchor (~0.48% risk)
    with a 2R target; production enforces a 1.5% ATR floor (~3x wider) aimed at a
    VA extension. Same price, different SL/TP geometry.
    """
    bars = _gentle_session()
    state, bar, sig = _find_green_signal(bars)
    assert sig is not None and sig.type == SignalType.BUY

    data = [bar_to_ohlc(b) for b in bars[:29]]
    amt = state_to_amt(state)
    prod_sig = build_entry_signal(
        direction="LONG",
        tick=bar_to_ohlc(bars[28]),
        amt_result=amt,
        ai_result={"rationale": "synthetic", "market_state": "Trending", "raw_output": "x"},
        setup_type=SetupType.TREND_MODEL,
        data=data,
        tick_size=TICK_SIZE,
    )
    green_risk = abs(float(sig.price) - float(sig.stop_loss))
    prod_risk = abs(float(prod_sig.price) - float(prod_sig.stop_loss))
    assert prod_risk / green_risk > 2.5
    assert sig.metadata["quant_rr"] == 2.0


def test_exit_engine_divergence():
    """Same position and bar sequence: greenfield stops out on bar 32 when the
    intrabar LOW pierces SL; production (close-based check_position) never exits
    the window. Agreement on only the three quiet post-entry bars.
    """
    bars = _gentle_session()
    state, bar, sig = _find_green_signal(bars)
    assert sig is not None

    gf_engine = GreenfieldExitEngine(time_stop_bars=30)
    prod_engine = ProdExitEngine()

    gf_pos = GreenfieldPosition(
        order=Order(sig, 1), open_price=float(sig.price), open_time=sig.timestamp, size=1
    )
    entry_ts = datetime(2025, 1, 15, 9, 30, 0, tzinfo=timezone.utc)
    prod_pos = ProdPosition(
        id="pos-1",
        symbol=SYMBOL,
        side=Side.LONG,
        entry_price=sig.price,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit,
        size=Decimal("1"),
        initial_stop=sig.stop_loss,
        entry_time=entry_ts.isoformat(),
    )

    coord = AuctionCoordinator()
    for b in bars[:29]:
        coord.on_bar_close(b)

    gf_first = None
    decisions = []
    for j in range(29, 60):
        b = bars[j]
        state = coord.on_bar_close(b)
        held = j - 28
        gd = gf_engine.evaluate(gf_pos, state, bar_index=held, bar_high=b.high, bar_low=b.low)
        ps = prod_engine.check_position(
            prod_pos, current_price=float(b.close), current_time=entry_ts.timestamp() + held * 5,
            time_to_close=0.0,
        )
        p_ok = ps is not None
        p_reason = ps.reason if ps else ""
        if gf_first is None and gd.should_exit:
            gf_first = (j, gd.reason)
        decisions.append((j, gd.should_exit, gd.reason, p_ok, p_reason))

    agree = sum(1 for d in decisions if d[1] == d[3])
    print(f"\n=== exit differential (bars 29..59, n={len(decisions)}): "
          f"agreement {agree}/{len(decisions)} ({agree / len(decisions) * 100:.1f}%)")
    for d in decisions:
        if d[2] or d[4]:
            print(f"  bar {d[0]} green=exit:{d[1]} {d[2]:8s} | prod=exit:{d[3]} {d[4]}")
        elif d[0] < 35:
            print(f"  bar {d[0]} green=exit:{d[1]} {d[2]:8s} | prod=exit:{d[3]} {d[4]}")

    assert gf_first == (32, "SL")
    assert not any(d[3] for d in decisions)
    assert agree == 3
    assert not all(d[1] for d in decisions)
