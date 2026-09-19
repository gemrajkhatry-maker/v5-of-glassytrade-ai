"""Characterization + table-parity tests for the rule-based AMT narrative.

These fixtures were recorded from the original inline implementation of
``LLMAdvisor._rule_based_narrative`` (quant/llm/advisor.py, pre-WS7) and are
asserted as exact literals. The table-driven implementation in
quant/llm/narrative.py must produce byte-identical dicts.

Rule families covered (in original evaluation order):
  MODE 1 (position open): tp_reached, vwap_exhaustion(L), opposing_flow(S),
    hold_healthy_trend, default_monitor
  MODE 2 guards: opening_noise, dead_market, contested_bubble, climax(±2σ)
  Playbooks: triple_a_aggression LONG (+ CVD-fail fall-through to fallback),
    second_drive_reclaim, initiative_breakdown, va_fade SHORT
  In-progress state machine: ABSORBING wait
  Fallbacks: mid-value neutral, lower-VA bullish CVD
"""

from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext


def make_ctx(**kw) -> DecisionContext:
    close = kw.pop("close", 24155.0)
    bar = Bar(
        time="2026-08-25T10:00:00+05:30",
        open=close - 5.0, high=close + 5.0, low=close - 10.0, close=close,
        volume=1500.0, buy_volume=800.0, sell_volume=700.0, delta=100.0, vwap=close - 3.0,
    )
    return DecisionContext(
        symbol="NIFTY",
        bar=bar,
        market_state=kw.pop("market_state", MarketState.BALANCED),
        poc=kw.pop("poc", 24155.3),
        vah=kw.pop("vah", 24220.0),
        val=kw.pop("val", 24100.0),
        session_phase=kw.pop("session_phase", "PRIMARY"),
        cvd_slope=kw.pop("cvd_slope", 5.0),
        absorption_side=kw.pop("absorption_side", ""),
        **kw,
    )


# name -> (fixture kwargs, expected narrative dict recorded verbatim)
CHARACTERIZATION_CASES = {
    # ── MODE 1: position management ──────────────────────────────────────
    "pos_tp_reached": (
        dict(position_open=True, position_side="LONG", position_entry_price=24100.0,
             position_tp=24150.0, position_sl=24050.0, position_bars_held=12),
        {
            "action": "TAKE_PROFIT", "direction": "LONG", "setup": "MANAGE_POSITION",
            "confidence": "High",
            "rationale": "Target reached on NIFTY LONG @ 24155.0 (TP: 24150.0, +55.0 pts). Take profit / trail tight.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "pos_long_vwap_exhaustion": (
        dict(position_open=True, position_side="LONG", position_entry_price=24100.0,
             position_tp=0.0, position_sl=24050.0, position_bars_held=8,
             vwap_upper_2=24100.0),
        {
            "action": "TAKE_PROFIT", "direction": "LONG", "setup": "MANAGE_POSITION",
            "confidence": "High",
            "rationale": "NIFTY LONG extended into VWAP +2σ (24100.0, +55.0 pts). Lock partial gains.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "pos_short_opposing_flow": (
        dict(position_open=True, position_side="SHORT", position_entry_price=24200.0,
             cvd_slope=3.0, position_sl=24280.0, position_bars_held=5),
        {
            "action": "TIGHTEN_SL", "direction": "SHORT", "setup": "MANAGE_POSITION",
            "confidence": "High",
            "rationale": "Opposing order flow detected on NIFTY SHORT (CVD +3.0). Tighten SL to protect capital.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "pos_hold_healthy_trend": (
        dict(position_open=True, position_side="LONG", position_entry_price=24100.0,
             position_tp=24300.0, position_sl=24050.0, position_bars_held=20,
             cvd_slope=1.2),
        {
            "action": "HOLD", "direction": "LONG", "setup": "MANAGE_POSITION",
            "confidence": "High",
            "rationale": "Holding NIFTY LONG from 24100.0 (+55.0 pts, 20 bars). Order flow healthy (CVD +1.2), targeting 24300.0.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "pos_default_monitor": (
        dict(position_open=True, position_side="LONG", position_entry_price=24100.0,
             position_tp=24300.0, position_sl=24050.0, position_bars_held=30,
             cvd_slope=-2.0),
        {
            "action": "HOLD", "direction": "LONG", "setup": "MANAGE_POSITION",
            "confidence": "Medium",
            "rationale": "Managing NIFTY LONG from 24100.0 (+55.0 pts), SL @ 24050.0. Standing by for next structural rotation.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    # ── MODE 2: guards ───────────────────────────────────────────────────
    "guard_opening_noise": (
        dict(session_phase="OPENING_NOISE"),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Low",
            "rationale": "Opening 15m session warmup on NIFTY. IB forming — accumulating initial balance.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "guard_dead_market": (
        dict(market_state=MarketState.DEAD),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Low",
            "rationale": "NIFTY — volume collapsed, auction structure absent. No trade.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "guard_contested_bubble": (
        dict(contested_bubble_zone=True),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Low",
            "rationale": "NIFTY — opposing institutional stacks on both sides. Contested zone: flat is the only trade.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "guard_climax_above_upper": (
        dict(vwap_upper_2=24100.0),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Low",
            "rationale": "NIFTY overextended above VWAP +2σ (24100.0) — climax risk, standing down.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "guard_climax_below_lower": (
        dict(close=24020.0, vwap_lower_2=24050.0),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Low",
            "rationale": "NIFTY overextended below VWAP −2σ (24050.0) — climax risk, standing down.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    # ── Playbooks ────────────────────────────────────────────────────────
    "play_triple_a_aggr_long": (
        dict(triple_a_phase="AGGRESSION", triple_a_signal="LONG", cvd_slope=2.0,
             poc=0.0, vah=0.0, val=0.0),
        {
            "action": "ENTER_LONG", "direction": "LONG", "setup": "TRIPLE_A",
            "confidence": "High",
            "rationale": "Triple-A AGGRESSION on NIFTY: absorption → accumulation → cluster close above level. CVD +2.0. Institutional LONG confirmed.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "play_triple_a_aggr_short_cvd_fails": (
        # AGGRESSION/SHORT but CVD not confirming → must fall through every
        # playbook and land in the generic fallback (order/short-circuit check).
        dict(triple_a_phase="AGGRESSION", triple_a_signal="SHORT", cvd_slope=0.5,
             poc=0.0, vah=0.0, val=0.0),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Medium",
            "rationale": "NIFTY in BALANCED state, near POC (0.0). Neutral order flow — no directional edge yet.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "play_second_drive": (
        dict(drive_entry_valid=True, drive_number=2, poc=24200.0),
        {
            "action": "ENTER_LONG", "direction": "LONG", "setup": "SECOND_DRIVE_D2",
            "confidence": "High",
            "rationale": "Second Drive LONG on NIFTY: D1 level rejected, D2 re-approach confirms failed auction. Price 24155.0 vs POC 24200.0. CVD +5.0.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "play_initiative_breakdown": (
        dict(break_type="INITIATIVE", break_direction="DOWN", cvd_slope=-1.5,
             vwap_upper_2=0.0),
        {
            "action": "ENTER_SHORT", "direction": "SHORT", "setup": "BREAKOUT",
            "confidence": "High",
            "rationale": "Initiative downside breakdown on NIFTY: close below VAL (24100.0), CVD -1.5. Trend continuation SHORT.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "play_va_fade_short": (
        dict(close=24250.0, vah=24220.0, poc=24155.3, cvd_slope=-2.0),
        {
            "action": "ENTER_SHORT", "direction": "SHORT", "setup": "VA_FADE",
            "confidence": "Medium",
            "rationale": "VA Fade SHORT on NIFTY: price 24250.0 probed above VAH (24220.0), seller CVD -2.0 rejecting probe. Target POC 24155.3.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "state_absorbing_wait": (
        dict(triple_a_phase="ABSORBING", triple_a_signal="LONG"),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Medium",
            "rationale": "NIFTY Triple-A in ABSORBING phase — waiting for AGGRESSION close above cluster. Do not front-run.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    # ── Fallback ─────────────────────────────────────────────────────────
    "fallback_midvalue_neutral": (
        dict(cvd_slope=0.5),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Medium",
            "rationale": "NIFTY in BALANCED state, mid-value near POC (24155.3). Neutral order flow — no directional edge yet.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
    "fallback_bullish_lower_va": (
        dict(close=24110.0),
        {
            "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE",
            "confidence": "Medium",
            "rationale": "NIFTY in BALANCED state, lower VA near VAL (24100.0). Bullish CVD +5.0 — awaiting pullback to VAL (24100.0) for long entry.",
            "source": "AMT_RULE", "symbol": "NIFTY",
        },
    ),
}


def test_characterization_table_matches_recorded_literals():
    """Every fixture must produce the byte-identical recorded narrative."""
    from quant.llm.narrative import build_rule_based_narrative

    for name, (kwargs, expected) in CHARACTERIZATION_CASES.items():
        ctx = make_ctx(**kwargs)
        got = build_rule_based_narrative(ctx)
        assert got == expected, f"parity broken for fixture {name!r}:\n  got:      {got!r}\n  expected: {expected!r}"


def test_rule_count_and_order_documented():
    """The rule table must expose its ordered rules for parity auditing."""
    from quant.llm import narrative

    rules = narrative.RULE_TABLE
    assert isinstance(rules, list)
    # 19 ordered rules: 6 position-management (incl. the constant-True
    # default monitor), 5 guards, 8 playbook/state-machine entries. The
    # location/bias commentary is the terminal builder, not a predicate rule.
    assert len(rules) == 19
    # Order sanity: position-management rules first, guards before playbooks.
    names = [name for name, _pred, _b in rules]
    assert names[0] == "position_take_profit"
    assert names[-1] == "state_machine_in_progress"
    assert names.index("opening_noise") < names.index("dead_market") < names.index("contested_bubble")
    assert names.index("va_fade_long") < names.index("state_machine_in_progress")


def test_advisor_shim_delegates_to_narrative_module():
    """LLMAdvisor._rule_based_narrative stays a delegating shim (callers unchanged)."""
    from quant.llm.advisor import LLMAdvisor
    from quant.llm import narrative

    adv = LLMAdvisor(emit_fn=None)
    try:
        for name, (kwargs, expected) in CHARACTERIZATION_CASES.items():
            ctx = make_ctx(**kwargs)
            assert adv._rule_based_narrative(ctx) == expected, name
            assert adv._rule_based_narrative(ctx) == narrative.build_rule_based_narrative(ctx)
    finally:
        adv.shutdown()


def test_rule_based_backend_satisfies_protocol():
    """RuleBasedAdvisoryBackend is interchangeable behind AdvisoryBackend Protocol."""
    from quant.llm.advisor import AdvisoryBackend
    from quant.llm.narrative import RuleBasedAdvisoryBackend

    backend = RuleBasedAdvisoryBackend()
    assert isinstance(backend, AdvisoryBackend)
    for name, (kwargs, expected) in CHARACTERIZATION_CASES.items():
        assert backend.analyze(make_ctx(**kwargs)) == expected, name


def test_mlx_backend_shares_protocol_shape():
    """MLXAdvisoryBackend exposes the same analyze() surface (structural typing)."""
    from quant.llm.advisor import AdvisoryBackend, LLMAdvisor, MLXAdvisoryBackend

    adv = LLMAdvisor(emit_fn=None, model_path="/nonexistent/model")
    try:
        backend = MLXAdvisoryBackend(adv)
        assert isinstance(backend, AdvisoryBackend)
        # No model loadable at that path → deterministic rule-based fallback path.
        out = backend.analyze(make_ctx(cvd_slope=0.5))
        assert out["source"] == "AMT_RULE"
    finally:
        adv.shutdown()


def test_injected_backend_overrides_baseline_emission():
    """A custom AdvisoryBackend fully owns the synchronous emission payload."""
    from quant.llm.advisor import LLMAdvisor

    class RecordingBackend:
        def __init__(self):
            self.calls = []

        def analyze(self, ctx):
            self.calls.append(ctx)
            return {"action": "CUSTOM", "source": "TEST"}

    emitted = []
    backend = RecordingBackend()
    adv = LLMAdvisor(emit_fn=lambda evt: emitted.append(evt), backend=backend)
    try:
        adv.on_context(make_ctx())
    finally:
        adv.shutdown()
    assert len(backend.calls) == 1
    assert len(emitted) == 1
    assert emitted[0].decision["action"] == "CUSTOM"


def test_pos_take_profit_tolerance():
    """Verify TP_TOUCH_TOLERANCE_PCT triggers take-profit narrative when price is within 0.2% of TP."""
    from quant.llm.narrative import build_rule_based_narrative, TP_TOUCH_TOLERANCE_PCT

    assert TP_TOUCH_TOLERANCE_PCT == 0.002

    # LONG position: TP = 10000. Price is 9985 (within 0.2% of 10000 = 9980 threshold)
    ctx_long = make_ctx(
        close=9985.0,
        position_open=True,
        position_side="LONG",
        position_entry_price=9800.0,
        position_tp=10000.0,
        position_sl=9700.0,
        position_bars_held=5,
    )
    res_long = build_rule_based_narrative(ctx_long)
    assert res_long["action"] == "TAKE_PROFIT"
    assert res_long["direction"] == "LONG"

    # SHORT position: TP = 10000. Price is 10015 (within 0.2% of 10000 = 10020 threshold)
    ctx_short = make_ctx(
        close=10015.0,
        position_open=True,
        position_side="SHORT",
        position_entry_price=10200.0,
        position_tp=10000.0,
        position_sl=10300.0,
        position_bars_held=5,
    )
    res_short = build_rule_based_narrative(ctx_short)
    assert res_short["action"] == "TAKE_PROFIT"
    assert res_short["direction"] == "SHORT"
