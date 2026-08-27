# tests/quant/runtime/test_opposing_signal_exit.py
"""Opposing-signal exit (thesis invalidation): a fresh contrary APPROVED
decision — evaluated on the positioned bar-close AFTER normal exit evaluation
declined — flattens the open position with reason OPPOSING_SIGNAL through the
base close path (counts as a trade via count_as_trade=True default).

Design constraints proven here:
  - Approval flows through the EXISTING DecisionService wrapper (gates +
    SignalBuilder qualification inherited) with allow_positioned=True bypassing
    ONLY gate 2's open-position blocker.
  - Same-direction approvals and NO_EDGE do nothing.
  - Real cooldown seconds still block under allow_positioned.
  - WITHOUT the flag, open-position contexts reject identically to today
    (gate name POSITION_COOLDOWN) — zero behavior change for existing paths.

Engine-driving pattern mirrors tests/quant/runtime/test_positive_approval.py
(organic ticks -> analyzer -> Triple-A -> gates -> approval, no mocks).
"""

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.events import DecisionProduced, PositionClosed
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine


def _signal(side="LONG", entry=100.0, sl=90.0, tp=120.0):
    """Same shape as the proven harness in test_tick_level_exits.py —
    r=10 so no trail/BE/sl threshold sits inside a small price range."""
    return Signal(
        type=side, reason="test", entry=entry, sl=sl, tp=tp,
        rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t",
    )


def _positioned_engine(ticks, symbol, side="LONG", entry=100.0):
    """Engine with an open position injected via the established test hook.

    ``entry`` is chosen OUTSIDE the fixture's price path so the injected
    trade survives the quiet phase untouched (BE floor below every low for a
    LONG; 0.8R trail/TP tiers far away) — only the flip can close it."""
    sl = entry - 10.0 if side == "LONG" else entry + 10.0
    eng = QuantEngine(
        SyntheticGateway(list(ticks)), symbol, interval_seconds=1,
        cooldown_bars=3,
    )
    # Bar-path CVD-kill would (correctly) close any position that contradicts
    # the fixture's session-long order-flow LONG before an organic approval
    # can form — that rule owns its own suite, so disable it locally to
    # exercise the thesis-flip machinery itself. Every other normal-exit rule
    # (SESSION_CLOSE/SL/spread/TP/trail/time) keeps full priority ahead of
    # the flip check.
    eng._exits.cvd_kill_threshold = float("inf")
    eng._position = eng._oms.submit(_signal(side=side, entry=entry, sl=sl), 1.0)
    eng._entry_bar_index = 0
    return eng


def _short_approval_ticks():
    """Exact mirror of the load-bearing organic approval recipe in
    tests/quant/runtime/test_positive_approval.py, flipped bearish:
      - ~150 quiet alternating bars with sell-dominant volume (negative CVD
        drift),
      - one zero-range 50x-volume BUY_ABSORBED spike (buyers absorbed ->
        bearish pending),
      - two displacement-down closes validating the absorption,
      - continued fall into Triple-A AGGRESSION SHORT -> full approval.
    """
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 1, 9)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 320, 180))   # BUY_ABSORBED spike
    out.append(Tick("t301", 100.0, 10, 4, 6))        # close the spike bar
    out.append(Tick("t302", 99.6, 20, 6, 14))        # displacement down -> APPROVES SHORT
    return out


def _quiet_ticks(n_bars=40):
    """Neutral alternating bars — proven never to approve without a Triple-A
    pulse (see test_decide_golden)."""
    out = []
    k = 0
    for _ in range(n_bars):
        out.append(Tick(f"t{k}", 99.95, 10, 6, 4))
        k += 1
        out.append(Tick(f"t{k}", 100.05, 10, 4, 6))
        k += 1
    return out


def test_contrary_approval_flattens_position():
    """Genuine SHORT approval while holding the injected LONG -> flatten,
    OPPOSING_SIGNAL counted as a trade, cooldown armed for the next entry."""
    # Entry below every fixture low: BE floor can never clip, so only the
    # flip can close. Two trailing ticks close the next bar post-flip so the
    # flat-path cooldown guard fires deterministically (reason COOLDOWN).
    eng = _positioned_engine(
        _short_approval_ticks()
        + [Tick("t400", 99.55, 10, 1, 9), Tick("t401", 99.50, 10, 1, 9)],
        "FLIP", side="LONG", entry=98.5,
    )
    trades_before = eng._risk.state().trades_today

    eng.run()

    assert eng._position is None, "contrary approval must flatten the position"
    closes = [e for e in eng.events if isinstance(e, PositionClosed)]
    assert closes, "flip must route through the base close path"
    assert closes[-1].fill.reason == "OPPOSING_SIGNAL"
    assert eng._risk.state().trades_today == trades_before + 1

    # The qualifying decision came through the pipeline with gate 2 passed
    # via the thesis-flip passthrough (SignalBuilder qualification upstream).
    approvals = [
        d for d in eng.events
        if isinstance(d, DecisionProduced) and d.decision.approved
    ]
    assert approvals[-1].decision.signal.type == "SHORT"
    g2 = next(r for r in approvals[-1].decision.gate_results if r.gate == 2)
    assert g2.passed and "thesis-flip" in g2.reason

    # Cooldown armed post-close: the NEXT evaluation is cooldown-blocked
    # normally (Guard 1 on the flat path — identical behavior to today).
    reasons = [
        d.decision.reason for d in eng.events if isinstance(d, DecisionProduced)
    ]
    assert reasons[-1] == "COOLDOWN"


def test_same_direction_approval_holds():
    """Mirror-bullish data (positive_approval recipe) approves LONG — the
    SAME direction as the held LONG — so the position must survive."""
    bullish = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 9, 1)
               for i in range(300)]
    bullish += [
        Tick("t300", 100.0, 500, 180, 320),   # SELL_ABSORBED spike (bullish)
        Tick("t301", 100.0, 10, 6, 4),
        Tick("t302", 100.4, 20, 14, 6),       # displacement up (validates)
        Tick("t303", 100.6, 20, 14, 6),
        Tick("t304", 100.8, 10, 9, 1),
        Tick("t305", 101.0, 10, 9, 1),
        Tick("t306", 101.2, 10, 9, 1),
    ]
    eng = _positioned_engine(bullish, "HOLD", side="LONG", entry=99.90)

    eng.run()

    approvals = [
        d for d in eng.events
        if isinstance(d, DecisionProduced) and d.decision.approved
    ]
    assert approvals, "fixture sanity: same-direction approval must occur"
    assert approvals[-1].decision.signal.type == "LONG"
    assert eng._position is not None, "same-direction approval must hold"
    assert not [e for e in eng.events if isinstance(e, PositionClosed)]


def test_gate_failure_no_flip():
    """No Triple-A pulse anywhere -> every positioned evaluation fails to
    approve -> nothing flips."""
    eng = _positioned_engine(_quiet_ticks(), "NOEDGE")

    eng.run()

    assert eng._position is not None, "gate failure must not flip"
    assert not [e for e in eng.events if isinstance(e, PositionClosed)]
    decisions = [d for d in eng.events if isinstance(d, DecisionProduced)]
    assert decisions
    assert all(not d.decision.approved and d.decision.signal is None
               for d in decisions)


def test_real_cooldown_still_blocks_even_allow_positioned():
    """allow_positioned bypasses ONLY the open-position blocker. A live
    cooldown (cooldown_remaining_sec > 0) still fails gate 2 even with the
    flag raised — including when BOTH blockers are present."""
    results = GatePipeline().evaluate(
        _ctx(position_open=True, cooldown_sec=120), allow_positioned=True
    )
    g2 = next(r for r in results if r.gate == 2)
    assert not g2.passed
    assert "In cooldown" in g2.reason


def test_flip_evaluation_runs_while_risk_halted():
    """Halts gate ENTRIES, not exits: with allow_positioned=True the
    DecisionService must NOT short-circuit to HALTED (default call shape
    still does — default-compat)."""
    from dataclasses import replace

    from quant.bars import Bar
    from quant.decision.decision_service import DecisionService

    halted = replace(
        _ctx(position_open=True, cooldown_sec=0),
        bar=Bar(time="t", open=100.0, high=100.0, low=100.0, close=100.0,
                volume=1.0),
        risk_halted=True,
    )
    assert DecisionService().evaluate(halted).reason == "HALTED"
    assert DecisionService().evaluate(
        halted, allow_positioned=True
    ).reason != "HALTED"


def test_default_compat_open_position_still_rejected_without_flag():
    """WITHOUT allow_positioned, an open-position context rejects exactly as
    today: gate 2 named POSITION_COOLDOWN, failed. No behavior change for
    every existing caller/test."""
    results = GatePipeline().evaluate(_ctx(position_open=True, cooldown_sec=0))
    g2 = next(r for r in results if r.gate == 2)
    assert not g2.passed
    assert g2.name == "POSITION_COOLDOWN"
    assert g2.reason == "Position already open"

    # ...while WITH the flag it passes through (thesis-flip eligibility).
    flagged = GatePipeline().evaluate(
        _ctx(position_open=True, cooldown_sec=0), allow_positioned=True
    )
    fg2 = next(r for r in flagged if r.gate == 2)
    assert fg2.passed


def _ctx(position_open: bool, cooldown_sec: float) -> DecisionContext:
    """Minimal DecisionContext isolating gate 2's two blockers."""
    return DecisionContext(
        symbol="SYM",
        session_open=True,
        warmup_complete=True,
        position_open=position_open,
        cooldown_remaining_sec=cooldown_sec,
    )
