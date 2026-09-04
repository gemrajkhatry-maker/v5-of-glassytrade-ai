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

from types import SimpleNamespace

import pytest

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
    position = eng._oms.submit(_signal(side=side, entry=entry, sl=sl), 1.0)
    # Set position in both state and position manager
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(position))
    eng._get_position_manager().current_position = position
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

    assert eng.state.position is None, "contrary approval must flatten the position"
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
    assert eng.state.position is not None, "same-direction approval must hold"
    assert not [e for e in eng.events if isinstance(e, PositionClosed)]


def test_gate_failure_no_flip():
    """No Triple-A pulse anywhere -> every positioned evaluation fails to
    approve -> nothing flips."""
    eng = _positioned_engine(_quiet_ticks(), "NOEDGE")

    eng.run()

    assert eng.state.position is not None, "gate failure must not flip"
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


# ---------------------------------------------------------------------------
# Underlying-basis parity (wave-4 T3): entries qualify on the UNDERLYING
# dto+bar when an underlying feed drives decisions — the thesis-flip check
# must consume the IDENTICAL context source, or skip if unavailable.
# ---------------------------------------------------------------------------

def _option_mode_engine(side="LONG", entry=100.0):
    """Positioned engine wired like the live option mode: an underlying feed
    is present (so entries qualify via the underlying dto/bar), while the
    positioned bar-exit path hands the OPTION dto/bar to the flip check."""
    sl = entry - 10.0 if side == "LONG" else entry + 10.0
    eng = QuantEngine(
        SyntheticGateway([Tick("t0", 100.0, 10, 5, 5)]), "OPT",
        interval_seconds=1, cooldown_bars=3,
        underlying_gateway=SyntheticGateway([Tick("u0", 50000.0, 10, 5, 5)]),
    )
    eng._exits.cvd_kill_threshold = float("inf")
    position = eng._oms.submit(_signal(side=side, entry=entry, sl=sl), 1.0)
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(position))
    eng._get_position_manager().current_position = position
    eng._entry_bar_index = 0
    return eng


def _spy_pipeline(eng):
    """Stub the STRATEGY seam (the flip now routes through should_enter, the
    same entry point entries use — see runtime._check_thesis_flip) with one
    that ALWAYS approves a fresh SHORT, recording the exact ctx it was handed
    (and the builder's (bar, dto) args)."""
    captured = {}

    def fake_build(bar, amt_dto, cooldown_remaining_sec):
        captured["bar"] = bar
        captured["dto"] = amt_dto
        return object()  # opaque ctx; the stub ignores it

    eng._build_context = fake_build

    def should_enter(ctx, *, allow_positioned=False):
        captured["ctx"] = ctx
        captured["allow_positioned"] = allow_positioned
        return SimpleNamespace(
            approved=True, signal=_signal(side="SHORT"), gate_results=[],
            reason="APPROVED", phase="", block_reasons=[], model_label="",
        )

    eng._strategy = SimpleNamespace(should_enter=should_enter)
    return captured


def _opt_bar(time="opt1", close=99.75):
    from quant.bars import Bar
    return Bar(time=time, open=100.0, high=100.5, low=99.5, close=close,
               volume=10)


def test_flip_never_evaluates_on_option_side_context():
    """Divergence: positioned in option mode, the positioned bar hands the
    flip check an OPTION dto/bar that would approve SHORT — but the entry
    basis (underlying) context is unavailable this bar. The flip must SKIP
    (conservative), not act on context that never qualified anything."""
    eng = _option_mode_engine()
    captured = _spy_pipeline(eng)
    opt_dto = {"marketState": "BALANCED", "note": "OPTION-SIDE NOISE"}

    from quant.events import PositionClosed
    eng._check_thesis_flip(opt_dto, _opt_bar())

    assert eng.state.position is not None, (
        "flip must not fire on option-side context (entry basis unavailable)"
    )
    assert not [e for e in eng.events if isinstance(e, PositionClosed)]
    assert "ctx" not in captured, "guard must skip BEFORE any evaluation"


def test_flip_consumes_identical_underlying_context_source():
    """Happy path parity: when the underlying dto+bar the entry path uses ARE
    available, the flip builds its context from EXACTLY those objects — not
    the option dto/bar the exit path handed it — and still executes the close
    at the caller bar's premium-scale price."""
    eng = _option_mode_engine()
    captured = _spy_pipeline(eng)
    from quant.bars import Bar
    und_bar = Bar(time="und1", open=50000.0, high=50100.0, low=49900.0,
                  close=50050.0, volume=10)
    eng._underlying_amt_dto = {"marketState": "BALANCED", "note": "UNDERLYING"}
    eng._last_underlying_bar = und_bar
    opt_bar = _opt_bar(close=99.75)

    from quant.events import PositionClosed
    eng._check_thesis_flip({"marketState": "BALANCED", "note": "OPTION"}, opt_bar)

    assert eng.state.position is None, "contrary approval on entry basis must flip"
    closes = [e for e in eng.events if isinstance(e, PositionClosed)]
    assert closes[-1].fill.reason == "OPPOSING_SIGNAL"
    # Context source == the EXACT objects entries qualify on:
    assert captured["bar"] is und_bar, "flip ctx bar must be the underlying bar"
    assert captured["dto"]["note"] == "UNDERLYING"
    # Execution stays on the caller bar's premium-scale close (1 lot @ 100):
    assert closes[-1].fill.pnl == pytest.approx((99.75 - 100.0) * 1.0), (
        "close must execute at the traded instrument's price, not underlying scale"
    )


def test_put_option_holds_on_short_and_flips_on_long():
    """Holding a PUT option: a fresh SHORT approval on underlying represents
    same-direction thesis and must HOLD. A fresh LONG approval represents a
    contrary thesis and must FLATTEN."""
    from quant.bars import Bar
    und_bar = Bar(time="u1", open=50000.0, high=50100.0, low=49900.0, close=50050.0, volume=10)

    # 1. Engine with PUT contract symbol
    eng = _option_mode_engine(side="LONG", entry=100.0)
    eng.symbol = "SILVERM 24 SEP 235000 PUT"
    eng._underlying_amt_dto = {"marketState": "BALANCED"}
    eng._last_underlying_bar = und_bar

    # Stub pipeline to approve SHORT
    def enter_short(ctx, *, allow_positioned=False):
        return SimpleNamespace(
            approved=True, signal=_signal(side="SHORT"), gate_results=[],
            reason="APPROVED", phase="", block_reasons=[], model_label="",
        )
    eng._strategy = SimpleNamespace(should_enter=enter_short)

    # A continuing SHORT signal must NOT close the PUT position
    eng._check_thesis_flip({"marketState": "BALANCED"}, _opt_bar(close=105.0))
    assert eng.state.position is not None, "PUT position must hold when underlying confirms SHORT"

    # 2. Now stub pipeline to approve LONG (contrary signal)
    def enter_long(ctx, *, allow_positioned=False):
        return SimpleNamespace(
            approved=True, signal=_signal(side="LONG"), gate_results=[],
            reason="APPROVED", phase="", block_reasons=[], model_label="",
        )
    eng._strategy = SimpleNamespace(should_enter=enter_long)

    # A contrary LONG signal MUST flatten the PUT position
    eng._check_thesis_flip({"marketState": "BALANCED"}, _opt_bar(close=95.0))
    assert eng.state.position is None, "PUT position must flatten when underlying flips to LONG"
