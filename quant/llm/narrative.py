"""Table-driven rule-based AMT narrative (extracted verbatim from advisor.py).

This module is PURE: no I/O, no threads, no model loading. It reads ONLY raw
DecisionContext fields and emits the structured narrative dict, preserving the
original evaluation order and short-circuit semantics exactly.

Extracted from ``LLMAdvisor._rule_based_narrative`` as WS7-lite: LLM advisory
is isolated behind an explicit interface so MLX-backed and rule-based backends
are interchangeable while the engine stays deterministic.

Rule families, in original evaluation order (19 ordered rules; first match
wins — short-circuit return):
  MODE 1 (position open): take-profit reached, VWAP ±2σ exhaustion (long and
    short), opposing order flow, healthy-trend hold, default position monitor
  MODE 2 guards: opening noise, dead market, contested bubble zone, climax
    beyond VWAP ±2σ (above then below)
  Playbooks: Triple-A AGGRESSION long/short (CVD-confirmed), Second-Drive
    reclaim, Initiative breakout up/down, VA fade long/short,
    state-machine-in-progress wait
  Terminal fallback builder: value-area location + CVD bias commentary.
"""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

from quant.decision.context import DecisionContext
from quant.contracts.enums import MarketState as _MS
from quant.contracts.vocabulary import is_opening_phase

# A rule is (name, predicate(ctx) -> bool, build(ctx) -> decision dict).
# RULE_TABLE is evaluated strictly in order; the first truthy predicate wins.
Rule = Tuple[
    str, Callable[[DecisionContext], bool], Callable[[DecisionContext], Dict[str, Any]]
]


def _px(c: DecisionContext) -> float:
    return c.bar.close if c.bar else 0.0


def _side(c: DecisionContext) -> str:
    return c.position_side or "LONG"


def _pnl_pts(c: DecisionContext) -> float:
    side = _side(c)
    px = _px(c)
    entry_px = c.position_entry_price or px
    return (px - entry_px) if side == "LONG" else (entry_px - px)


def _action(
    action: str, direction: str, setup: str, confidence: str, rationale: str, sym: str
) -> Dict[str, Any]:
    return {
        "action": action,
        "direction": direction,
        "setup": setup,
        "confidence": confidence,
        "rationale": rationale,
        "source": "AMT_RULE",
        "symbol": sym,
    }


# ── MODE 1: ACTIVE POSITION MANAGEMENT (Fabio Overseer) ────────────────────


def _pos_take_profit_pred(c: DecisionContext) -> bool:
    # 1. Take profit target reached or close (MODE 1 gate: position_open)
    if not c.position_open:
        return False
    side = _side(c)
    tp = c.position_tp
    px = _px(c)
    return bool(
        tp > 0
        and (
            (side == "LONG" and px >= tp * 0.998)
            or (side == "SHORT" and px <= tp * 1.002)
        )
    )


def _pos_take_profit_build(c: DecisionContext) -> Dict[str, Any]:
    side = _side(c)
    px = _px(c)
    sym = c.symbol
    pnl = _pnl_pts(c)
    return _action(
        "TAKE_PROFIT",
        side,
        "MANAGE_POSITION",
        "High",
        f"Target reached on {sym} {side} @ {px:.1f} (TP: {c.position_tp:.1f}, +{pnl:.1f} pts). Take profit / trail tight.",
        sym,
    )


def _pos_long_vwap_exhaustion_pred(c: DecisionContext) -> bool:
    # 2. Overextension exhaustion (VWAP ±2σ), long leg
    return bool(
        c.position_open
        and _side(c) == "LONG"
        and c.vwap_upper_2 > 0
        and _px(c) >= c.vwap_upper_2
    )


def _pos_short_vwap_exhaustion_pred(c: DecisionContext) -> bool:
    return bool(
        c.position_open
        and _side(c) == "SHORT"
        and c.vwap_lower_2 > 0
        and _px(c) <= c.vwap_lower_2
    )


def _vwap_exhaustion_build(
    c: DecisionContext, band: float, sigma_label: str
) -> Dict[str, Any]:
    side = _side(c)
    sym = c.symbol
    pnl = _pnl_pts(c)
    return _action(
        "TAKE_PROFIT",
        side,
        "MANAGE_POSITION",
        "High",
        f"{sym} {side} extended into VWAP {sigma_label} ({band:.1f}, +{pnl:.1f} pts). Lock partial gains.",
        sym,
    )


def _pos_long_exhaustion_build(c: DecisionContext) -> Dict[str, Any]:
    return _vwap_exhaustion_build(c, c.vwap_upper_2, "+2σ")


def _pos_short_exhaustion_build(c: DecisionContext) -> Dict[str, Any]:
    return _vwap_exhaustion_build(c, c.vwap_lower_2, "−2σ")


def _pos_opposing_flow_pred(c: DecisionContext) -> bool:
    # 3. Opposing institutional order flow (tighten stop)
    if not c.position_open:
        return False
    side = _side(c)
    return bool(
        (
            side == "LONG"
            and (c.absorption_side == "SELL_ABSORBED" or c.cvd_slope < -2.0)
        )
        or (
            side == "SHORT"
            and (c.absorption_side == "BUY_ABSORBED" or c.cvd_slope > 2.0)
        )
    )


def _pos_opposing_flow_build(c: DecisionContext) -> Dict[str, Any]:
    side = _side(c)
    sym = c.symbol
    return _action(
        "TIGHTEN_SL",
        side,
        "MANAGE_POSITION",
        "High",
        f"Opposing order flow detected on {sym} {side} (CVD {c.cvd_slope:+.1f}). Tighten SL to protect capital.",
        sym,
    )


def _pos_healthy_trend_pred(c: DecisionContext) -> bool:
    # 4. Healthy trend continuation — HOLD
    if not c.position_open:
        return False
    side = _side(c)
    cvd_confirms = (side == "LONG" and c.cvd_slope > -0.5) or (
        side == "SHORT" and c.cvd_slope < 0.5
    )
    return bool(cvd_confirms and _pnl_pts(c) >= 0)


def _pos_healthy_trend_build(c: DecisionContext) -> Dict[str, Any]:
    side = _side(c)
    px = _px(c)
    entry_px = c.position_entry_price or px
    pnl = (px - entry_px) if side == "LONG" else (entry_px - px)
    tp_str = f", targeting {c.position_tp:.1f}" if c.position_tp > 0 else ""
    sym = c.symbol
    return _action(
        "HOLD",
        side,
        "MANAGE_POSITION",
        "High",
        f"Holding {sym} {side} from {entry_px:.1f} (+{pnl:.1f} pts, {c.position_bars_held} bars). Order flow healthy (CVD {c.cvd_slope:+.1f}){tp_str}.",
        sym,
    )


def _pos_default_monitor_pred(c: DecisionContext) -> bool:
    # 5. Default position hold / monitor SL — terminal rule of MODE 1
    return bool(c.position_open)


def _pos_default_monitor_build(c: DecisionContext) -> Dict[str, Any]:
    side = _side(c)
    px = _px(c)
    entry_px = c.position_entry_price or px
    pnl = (px - entry_px) if side == "LONG" else (entry_px - px)
    sl_str = f", SL @ {c.position_sl:.1f}" if c.position_sl > 0 else ""
    sym = c.symbol
    return _action(
        "HOLD",
        side,
        "MANAGE_POSITION",
        "Medium",
        f"Managing {sym} {side} from {entry_px:.1f} ({pnl:+.1f} pts){sl_str}. Standing by for next structural rotation.",
        sym,
    )


# ── MODE 2: ENTRY EVALUATION guards ────────────────────────────────────────


def _opening_noise_pred(c: DecisionContext) -> bool:
    # Guard 1: Opening noise — IB still forming
    return is_opening_phase(c.session_phase)


def _opening_noise_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Low",
        f"Opening 15m session warmup on {sym}. IB forming — accumulating initial balance.",
        sym,
    )


def _dead_market_pred(c: DecisionContext) -> bool:
    # Guard 2: Dead market — no auction structure
    ms_val = getattr(c.market_state, "value", c.market_state)
    return ms_val in (_MS.DEAD.value, _MS.DEAD, "DEAD_MARKET")


def _dead_market_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Low",
        f"{sym} — volume collapsed, auction structure absent. No trade.",
        sym,
    )


def _contested_bubble_pred(c: DecisionContext) -> bool:
    # Guard 3: Contested bubble zone — both BUY and SELL stacks present.
    return bool(getattr(c, "contested_bubble_zone", False))


def _contested_bubble_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Low",
        f"{sym} — opposing institutional stacks on both sides. Contested zone: flat is the only trade.",
        sym,
    )


def _climax_above_pred(c: DecisionContext) -> bool:
    # Guard 4: Anti-climax — price beyond VWAP ±2σ (raw bands), upper leg
    return bool(c.vwap_upper_2 > 0 and _px(c) > c.vwap_upper_2)


def _climax_above_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Low",
        f"{sym} overextended above VWAP +2σ ({c.vwap_upper_2:.1f}) — climax risk, standing down.",
        sym,
    )


def _climax_below_pred(c: DecisionContext) -> bool:
    return bool(c.vwap_lower_2 > 0 and _px(c) < c.vwap_lower_2)


def _climax_below_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Low",
        f"{sym} overextended below VWAP −2σ ({c.vwap_lower_2:.1f}) — climax risk, standing down.",
        sym,
    )


# ── Playbooks ──────────────────────────────────────────────────────────────


def _triple_a_long_pred(c: DecisionContext) -> bool:
    # Playbook A: Triple-A AGGRESSION long — CVD must confirm.
    return bool(
        (getattr(c, "triple_a_phase", "") or "") == "AGGRESSION"
        and (getattr(c, "triple_a_signal", "") or "") == "LONG"
        and c.cvd_slope > -0.5
    )


def _triple_a_long_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "ENTER_LONG",
        "LONG",
        "TRIPLE_A",
        "High",
        (
            f"Triple-A AGGRESSION on {sym}: absorption → accumulation → cluster close above level. "
            f"CVD +{c.cvd_slope:.1f}. Institutional LONG confirmed."
        ),
        sym,
    )


def _triple_a_short_pred(c: DecisionContext) -> bool:
    return bool(
        (getattr(c, "triple_a_phase", "") or "") == "AGGRESSION"
        and (getattr(c, "triple_a_signal", "") or "") == "SHORT"
        and c.cvd_slope < 0.5
    )


def _triple_a_short_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "ENTER_SHORT",
        "SHORT",
        "TRIPLE_A",
        "High",
        (
            f"Triple-A AGGRESSION on {sym}: absorption → accumulation → cluster close below level. "
            f"CVD {c.cvd_slope:.1f}. Institutional SHORT confirmed."
        ),
        sym,
    )


def _second_drive_pred(c: DecisionContext) -> bool:
    # Playbook B: Second-Drive Reclaim — 3+ drives = exhausted, skip.
    drive_valid = getattr(c, "drive_entry_valid", False)
    drive_number = getattr(c, "drive_number", 0)
    return bool(drive_valid and drive_number < 3)


def _second_drive_build(c: DecisionContext) -> Dict[str, Any]:
    px = _px(c)
    direction = "LONG" if px < c.poc else "SHORT"
    sym = c.symbol
    return _action(
        f"ENTER_{direction}",
        direction,
        "TRIPLE_A",
        "High",
        (
            f"Second Drive {direction} on {sym}: D1 level rejected, D2 re-approach confirms failed auction. "
            f"Price {px:.1f} vs POC {c.poc:.1f}. CVD {c.cvd_slope:+.1f}."
        ),
        sym,
    )


def _initiative_up_pred(c: DecisionContext) -> bool:
    # Playbook C: Initiative Breakout up — only tradeable if CVD confirms.
    btype = getattr(c, "break_type", "") or ""
    bdir = getattr(c, "break_direction", "") or ""
    return bool(btype == "INITIATIVE" and bdir == "UP" and c.cvd_slope > 0)


def _initiative_up_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "ENTER_LONG",
        "LONG",
        "BREAKOUT",
        "High",
        (
            f"Initiative upside breakout on {sym}: close above VAH ({c.vah:.1f}), "
            f"CVD +{c.cvd_slope:.1f}. Trend continuation LONG."
        ),
        sym,
    )


def _initiative_down_pred(c: DecisionContext) -> bool:
    btype = getattr(c, "break_type", "") or ""
    bdir = getattr(c, "break_direction", "") or ""
    return bool(btype == "INITIATIVE" and bdir == "DOWN" and c.cvd_slope < 0)


def _initiative_down_build(c: DecisionContext) -> Dict[str, Any]:
    sym = c.symbol
    return _action(
        "ENTER_SHORT",
        "SHORT",
        "BREAKOUT",
        "High",
        (
            f"Initiative downside breakdown on {sym}: close below VAL ({c.val:.1f}), "
            f"CVD {c.cvd_slope:.1f}. Trend continuation SHORT."
        ),
        sym,
    )


def _va_fade_long_pred(c: DecisionContext) -> bool:
    # Playbook D: VA Fade long — probe below VAL rejected by buyer CVD.
    px = _px(c)
    return bool(c.val > 0 and px < c.val and c.cvd_slope > 0 and c.poc > px)


def _va_fade_long_build(c: DecisionContext) -> Dict[str, Any]:
    px = _px(c)
    sym = c.symbol
    return _action(
        "ENTER_LONG",
        "LONG",
        "VA_FADE",
        "Medium",
        (
            f"VA Fade LONG on {sym}: price {px:.1f} probed below VAL ({c.val:.1f}), "
            f"buyer CVD +{c.cvd_slope:.1f} rejecting probe. Target POC {c.poc:.1f}."
        ),
        sym,
    )


def _va_fade_short_pred(c: DecisionContext) -> bool:
    px = _px(c)
    return bool(c.vah > 0 and px > c.vah and c.cvd_slope < 0 and c.poc < px)


def _va_fade_short_build(c: DecisionContext) -> Dict[str, Any]:
    px = _px(c)
    sym = c.symbol
    return _action(
        "ENTER_SHORT",
        "SHORT",
        "VA_FADE",
        "Medium",
        (
            f"VA Fade SHORT on {sym}: price {px:.1f} probed above VAH ({c.vah:.1f}), "
            f"seller CVD {c.cvd_slope:.1f} rejecting probe. Target POC {c.poc:.1f}."
        ),
        sym,
    )


def _state_machine_in_progress_pred(c: DecisionContext) -> bool:
    # In-progress Triple-A state machine — do not front-run.
    phase = getattr(c, "triple_a_phase", "") or ""
    return bool(phase in ("ABSORBING", "ACCUMULATING"))


def _state_machine_in_progress_build(c: DecisionContext) -> Dict[str, Any]:
    phase = getattr(c, "triple_a_phase", "") or ""
    tsig = getattr(c, "triple_a_signal", "") or ""
    waiting_for = (
        "AGGRESSION close above cluster"
        if tsig == "LONG"
        else "AGGRESSION close below cluster"
    )
    sym = c.symbol
    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Medium",
        (
            f"{sym} Triple-A in {phase} phase — "
            f"waiting for {waiting_for}. Do not front-run."
        ),
        sym,
    )


# ── Ordered rule table (first truthy predicate wins — short-circuit) ───────

RULE_TABLE: List[Rule] = [
    # MODE 1: active position management
    ("position_take_profit", _pos_take_profit_pred, _pos_take_profit_build),
    (
        "position_vwap_exhaustion_long",
        _pos_long_vwap_exhaustion_pred,
        _pos_long_exhaustion_build,
    ),
    (
        "position_vwap_exhaustion_short",
        _pos_short_vwap_exhaustion_pred,
        _pos_short_exhaustion_build,
    ),
    ("position_opposing_flow", _pos_opposing_flow_pred, _pos_opposing_flow_build),
    ("position_healthy_trend_hold", _pos_healthy_trend_pred, _pos_healthy_trend_build),
    ("position_default_monitor", _pos_default_monitor_pred, _pos_default_monitor_build),
    # MODE 2: entry-evaluation guards
    ("opening_noise", _opening_noise_pred, _opening_noise_build),
    ("dead_market", _dead_market_pred, _dead_market_build),
    ("contested_bubble", _contested_bubble_pred, _contested_bubble_build),
    ("climax_above_upper_band", _climax_above_pred, _climax_above_build),
    ("climax_below_lower_band", _climax_below_pred, _climax_below_build),
    # Playbooks
    ("triple_a_aggression_long", _triple_a_long_pred, _triple_a_long_build),
    ("triple_a_aggression_short", _triple_a_short_pred, _triple_a_short_build),
    ("second_drive_reclaim", _second_drive_pred, _second_drive_build),
    ("initiative_breakout_up", _initiative_up_pred, _initiative_up_build),
    ("initiative_breakdown_down", _initiative_down_pred, _initiative_down_build),
    ("va_fade_long", _va_fade_long_pred, _va_fade_long_build),
    ("va_fade_short", _va_fade_short_pred, _va_fade_short_build),
    (
        "state_machine_in_progress",
        _state_machine_in_progress_pred,
        _state_machine_in_progress_build,
    ),
]


def _fallback_commentary_build(c: DecisionContext) -> Dict[str, Any]:
    """Fallback: value-area location + CVD bias commentary (terminal builder)."""
    px = _px(c)
    state_str = str(
        c.market_state.value if hasattr(c.market_state, "value") else c.market_state
    )
    sym = c.symbol

    if c.vah > 0 and c.val > 0:
        va_range = max(c.vah - c.val, 0.01)
        pct = (px - c.val) / va_range
        if pct < 0.25:
            location = f"lower VA near VAL ({c.val:.1f})"
        elif pct > 0.75:
            location = f"upper VA near VAH ({c.vah:.1f})"
        else:
            location = f"mid-value near POC ({c.poc:.1f})"
    else:
        location = f"near POC ({c.poc:.1f})"

    if c.cvd_slope > 3.0:
        bias = f"Bullish CVD +{c.cvd_slope:.1f} — awaiting pullback to VAL ({c.val:.1f}) for long entry"
    elif c.cvd_slope < -3.0:
        bias = f"Bearish CVD {c.cvd_slope:.1f} — awaiting rally to VAH ({c.vah:.1f}) for short entry"
    else:
        bias = "Neutral order flow — no directional edge yet"

    return _action(
        "FLAT",
        "FLAT",
        "NO_EDGE",
        "Medium",
        f"{sym} in {state_str} state, {location}. {bias}.",
        sym,
    )


def build_rule_based_narrative(ctx: DecisionContext) -> Dict[str, Any]:
    """Evaluate RULE_TABLE in order against ctx; first match wins.

    Mirrors the original inline if-chain exactly: identical evaluation order,
    identical predicates, identical short-circuit returns, and the identical
    location/bias commentary when every playbook predicate fails.
    """
    for _name, pred, build in RULE_TABLE:
        if pred(ctx):
            return build(ctx)
    return _fallback_commentary_build(ctx)


@runtime_checkable
class AdvisoryBackend(Protocol):
    """Explicit seam between the trading engine and LLM advisory (WS7).

    Implementations must be callable synchronously with a DecisionContext and
    return a structured narrative dict (or None when nothing should be said).
    RuleBasedAdvisoryBackend is the deterministic default; the MLX-backed path
    in advisor.py satisfies the same Protocol.
    """

    def analyze(self, ctx: DecisionContext) -> Optional[Dict[str, Any]]: ...


class RuleBasedAdvisoryBackend:
    """Deterministic, dependency-free AdvisoryBackend (no model, ~0ms)."""

    def analyze(self, ctx: DecisionContext) -> Optional[Dict[str, Any]]:
        return build_rule_based_narrative(ctx)
