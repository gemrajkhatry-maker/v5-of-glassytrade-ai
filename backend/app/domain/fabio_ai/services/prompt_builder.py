"""Pure prompt construction and response parsing for LLM entry and overseer.

All functions are stateless and side-effect-free — no I/O, no threading.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, FootprintCandle
    from app.domain.fabio_ai.services.session_context import SessionInfo

logger = logging.getLogger(__name__)


# =====================================================================
# Entry prompt builder (extracted from GenerativeAIService._build_prompt)
# =====================================================================

def build_entry_prompt(data: Dict[str, Any]) -> str:
    """Build entry prompt aligned with Fabio Valentini's AMT playbook.

    7-section structured prompt:
    1. Session Structure: Prior levels, gap, IB, opening bias
    2. Market State: Balance/Imbalance, acceptance/rejection
    3. VP Levels: POC, VAH, VAL, LVN, HVN, shape, POC migration
    4. Break State: Initiative/responsive/absorption
    5. Order Flow: Delta, CVD, aggressive prints, LVN play
    6. Option Context: IV, delta, OI, theta
    7. Strategy Hint: Session phase + active model
    """
    price = data.get("ltp", 0)
    vah = data.get("vah", 0)
    val = data.get("val", 0)
    poc = data.get("poc", 0)
    delta = data.get("delta", 0)
    market_state = data.get("market_state", "Balanced")
    volume = data.get("volume", 0)
    delta_int = int(round(delta))
    delta_ratio = abs(delta) / volume if volume > 0 else 0
    is_aggressive = delta_ratio > 0.15
    is_balanced = "Balanced" in str(market_state)

    parts: list[str] = []

    # ── §1 SESSION STRUCTURE ─────────────────────────────────────────
    # Prior day levels
    prior_poc = data.get("prior_poc", 0)
    prior_vah = data.get("prior_vah", 0)
    prior_val = data.get("prior_val", 0)
    if prior_poc > 0:
        parts.append(f"PRIOR SESSION: POC {prior_poc:.0f}, VAH {prior_vah:.0f}, VAL {prior_val:.0f}.")

    # Gap classification
    gap_type = data.get("gap_type", "")
    opening_bias = data.get("opening_bias", "")
    if gap_type:
        parts.append(f"Gap: {gap_type}.")
    if opening_bias and opening_bias != "NEUTRAL":
        parts.append(f"Opening inventory: {opening_bias}.")

    # Initial Balance
    ib_high = data.get("ib_high", 0)
    ib_low = data.get("ib_low", 0)
    ib_complete = data.get("ib_complete", False)
    if ib_high > 0 and ib_low > 0:
        status = "complete" if ib_complete else "forming"
        parts.append(f"IB ({status}): {ib_low:.0f}-{ib_high:.0f} (range {ib_high - ib_low:.0f}).")

    # Opening relation
    opening_relation = data.get("opening_relation", "")
    if opening_relation == "OUT_ABOVE":
        parts.append("Open above prior VA — bullish initiative.")
    elif opening_relation == "OUT_BELOW":
        parts.append("Open below prior VA — bearish initiative.")

    # ── §2 MARKET STATE ──────────────────────────────────────────────
    has_displacement = data.get("has_displacement", False)
    acceptance_above = data.get("acceptance_above", False)
    acceptance_below = data.get("acceptance_below", False)
    rejection_high = data.get("rejection_at_high", False)
    rejection_low = data.get("rejection_at_low", False)
    velocity = data.get("price_velocity", 0.0)

    if is_balanced:
        parts.append("MARKET STATE: Balance. Price rotating around fair value.")
        parts.append("Active model: MEAN REVERSION.")
    else:
        parts.append("MARKET STATE: Imbalance. Directional displacement detected.")
        parts.append("Active model: TREND CONTINUATION.")

    if acceptance_above:
        parts.append("ACCEPTANCE above VAH — value migrating higher.")
    if acceptance_below:
        parts.append("ACCEPTANCE below VAL — value migrating lower.")
    if rejection_high:
        parts.append("REJECTION at VAH — wick rejection with volume spike.")
    if rejection_low:
        parts.append("REJECTION at VAL — wick rejection with volume spike.")
    if velocity > 0.5:
        parts.append(f"High velocity: {velocity:.2f} pts/s.")

    # Balance ratio
    balance_ratio = data.get("balance_ratio", 0)
    if balance_ratio > 0:
        parts.append(f"Balance ratio: {balance_ratio:.0%} inside VA.")

    # Market structure (5-state classifier)
    mkt_struct = data.get("market_structure", "")
    struct_conf = data.get("structure_confidence", 0)
    if mkt_struct and mkt_struct != "BALANCE":
        parts.append(f"Structure: {mkt_struct} ({struct_conf}/100).")

    # ── §3 VP LEVELS ─────────────────────────────────────────────────
    if val > 0 and price > 0:
        if price <= val * 1.002:
            parts.append(f"Price at VAL ({val:.0f}).")
        elif price >= vah * 0.998:
            parts.append(f"Price at VAH ({vah:.0f}).")
        elif poc > 0 and abs(price - poc) / poc < 0.003:
            parts.append(f"Price at POC ({poc:.0f}).")
        elif poc > 0:
            parts.append(f"Price {price:.0f}. POC {poc:.0f}, VAH {vah:.0f}, VAL {val:.0f}.")
    else:
        parts.append(f"Price {price:.0f}.")

    # LVN levels
    lvns = data.get("lvns", ())
    if lvns:
        lvn_str = ", ".join(f"{l:.0f}" for l in lvns[:3])
        near_lvn = any(abs(price - l) / price < 0.003 for l in lvns[:3]) if price > 0 else False
        if near_lvn:
            parts.append(f"ENTRY ZONE: Price at LVN ({lvn_str}).")
        else:
            parts.append(f"LVNs: {lvn_str}.")

    # HVN levels
    hvns = data.get("hvns", ())
    if hvns:
        parts.append(f"HVNs: {', '.join(f'{h:.0f}' for h in hvns[:3])}.")

    # POC migration signal
    poc_signal = data.get("poc_signal", "")
    poc_vs_price = data.get("poc_vs_price", "")
    if poc_signal:
        parts.append(f"POC migration: {poc_signal} ({poc_vs_price}).")

    # Profile shape
    profile_shape = data.get("profile_shape", "")
    _ps = profile_shape.lower() if profile_shape else ""
    if _ps == "P":
        parts.append("P-shape: long liquidation.")
    elif _ps == "B":
        parts.append("B-shape: bimodal, potential breakout.")
    elif _ps == "b":
        parts.append("b-shape: short covering.")
    elif _ps == "D":
        parts.append("D-shape: balanced rotation.")

    # Displacement leg
    leg_poc = data.get("leg_poc", 0)
    leg_lvns = data.get("leg_lvns", ())
    if has_displacement and leg_poc > 0:
        parts.append(f"Displacement leg POC: {leg_poc:.0f}.")
        if leg_lvns:
            parts.append(f"Leg LVNs: {', '.join(f'{l:.0f}' for l in leg_lvns[:3])}.")

    # ── §4 BREAK STATE ───────────────────────────────────────────────
    break_type = data.get("break_type", "")
    break_dir = data.get("break_direction", "")
    break_level = data.get("break_level", 0)
    if break_type:
        parts.append(f"BREAK: {break_type} {break_dir} at {break_level:.0f}.")
        if break_type == "INITIATIVE":
            parts.append("Volume-confirmed breakout — favor trend continuation.")
        elif break_type == "RESPONSIVE":
            parts.append("Failed push — favor mean reversion back into value.")
        elif break_type == "ABSORPTION":
            parts.append("Hidden delta at level — large player absorbing orders.")

    # ── §5 ORDER FLOW ────────────────────────────────────────────────
    if is_aggressive:
        if delta_int > 0:
            parts.append(f"Aggressive BUYING. Delta +{delta_int} ({delta_ratio:.0%}).")
        else:
            parts.append(f"Aggressive SELLING. Delta {delta_int} ({delta_ratio:.0%}).")
    else:
        parts.append(f"Delta {delta_int:+d} (no aggression).")

    # Volume bubbles
    volume_bubbles = data.get("volume_bubbles", "")
    if volume_bubbles:
        parts.append(f"Volume bubbles: {volume_bubbles}.")

    # Stacked imbalances from footprint
    stacked = data.get("stacked_imbalances", "")
    if stacked:
        parts.append(f"{stacked}.")

    # CVD
    cvd_div = data.get("cvd_divergence", "")
    cvd_slope = data.get("cvd_slope", 0.0)
    if cvd_div == "BEARISH_DIV":
        parts.append("CVD BEARISH DIVERGENCE — buying pressure declining.")
    elif cvd_div == "BULLISH_DIV":
        parts.append("CVD BULLISH DIVERGENCE — selling pressure declining.")
    elif cvd_slope > 0.5:
        parts.append("CVD up — sustained buying.")
    elif cvd_slope < -0.5:
        parts.append("CVD down — sustained selling.")

    # LVN play signal
    lvn_play = data.get("lvn_play")
    if lvn_play:
        parts.append(
            f"LVN PLAY: {lvn_play['direction']} at {lvn_play['lvn_price']:.0f} "
            f"(vol {lvn_play['velocity_ratio']:.1f}x, "
            f"rej={'Y' if lvn_play['has_rejection'] else 'N'}, "
            f"flip={'Y' if lvn_play['has_delta_flip'] else 'N'}) "
            f"→ target {lvn_play['target']:.0f}."
        )

    # ── §6 OPTION CONTEXT ────────────────────────────────────────────
    greeks = data.get("greeks")
    if greeks:
        g_parts = []
        if greeks.get("iv", 0) > 0:
            g_parts.append(f"IV={greeks['iv']:.1f}%")
        if greeks.get("delta", 0) != 0:
            g_parts.append(f"Delta={greeks['delta']:.2f}")
        if greeks.get("theta", 0) != 0:
            g_parts.append(f"Theta={greeks['theta']:.2f}")
        if greeks.get("gamma", 0) != 0:
            g_parts.append(f"Gamma={greeks['gamma']:.4f}")
        if g_parts:
            parts.append(f"Options: {', '.join(g_parts)}.")

    # OI analysis
    oi_action = data.get("oi_action", "")
    if oi_action and oi_action != "NEUTRAL":
        parts.append(f"OI: {oi_action}.")
    oi_pcr = data.get("oi_pcr", 0)
    if oi_pcr > 0:
        parts.append(f"PCR: {oi_pcr:.2f}.")

    # ── §7 STRATEGY + SIGNALS ────────────────────────────────────────
    # ML model signal
    ml_signal = data.get("ml_signal")
    if ml_signal:
        ml_dir = ml_signal.get("direction", "")
        ml_prob = ml_signal.get("probability", 0)
        ml_regime = ml_signal.get("regime", "")
        parts.append(f"ML: {ml_dir} ({ml_prob:.0%}, {ml_regime}).")

    # Strategy hint
    strategy_hint = data.get("strategy_hint", "")
    if strategy_hint:
        parts.append(strategy_hint)

    # Episodic memory
    episodic_memory = data.get("episodic_memory", "")
    if episodic_memory:
        parts.append(episodic_memory)

    # ── DECISION FRAMEWORK ───────────────────────────────────────────
    parts.append(
        "RULES: "
        "1) Market State → active model (Trend or Mean Reversion). "
        "2) Price at LVN/IB/VA boundary → entry zone. "
        "3) Order flow confirms direction (delta + CVD + volume). "
        "ALL THREE must align. If LVN play detected, weigh heavily. "
        "If break is INITIATIVE, favor continuation. If RESPONSIVE, favor fade. "
        "Stay FLAT if no confluence."
    )

    narrative = " ".join(parts)

    from app.config import settings
    if settings.ALLOW_SHORT:
        dir_choices = '"LONG" | "SHORT" | "FLAT"'
    else:
        dir_choices = '"LONG" | "FLAT"'

    json_instruction = (
        "\n\nRespond ONLY with a JSON object:\n"
        '{"direction": ' + dir_choices + ', '
        '"rationale": "<brief explanation referencing market state + location + aggression>", '
        '"confidence": "High" | "Medium" | "Low", '
        '"market_state": "<Balance or Imbalance>"}'
    )

    return narrative + json_instruction


# =====================================================================
# Entry response parser (extracted from GenerativeAIService._parse_response)
# =====================================================================

_RE_TRIGGER = re.compile(r'trigger:\s*(.+?)(?:\n|\.\s|$)', re.IGNORECASE)
_RE_LOGIC = re.compile(r'logic:\s*(.+?)(?:\n|\.\s|trigger)', re.IGNORECASE)

_TRIGGER_LONG = [
    "enter long", "long with size", "long on pullback", "long on any dip",
    "long on re-entry", "long into", "add to longs", "re-enter long",
    "long with target", "long with full", "long hold", "buy on dip",
    "bullish bias", "buyers in control", "bullish momentum", "buy signal",
    "long entry", "favor long", "favour long", "go long",
    "rising market", "price rising", "bullish trend",
    "imbalanced (bullish)", "trending up", "price moving up",
    "aggressive buying", "call options trending",
    "bullish pressure", "bullish. ",
]
_TRIGGER_SHORT = [
    "enter short", "short on confirmation", "short with target",
    "short or", "short with", "short on rotation", "short with size",
    "buyers exhausted", "buyers are trapped", "failed breakout",
    "bearish bias", "sellers in control", "bearish momentum", "sell signal",
    "short entry", "favor short", "favour short", "go short", "bearish trend",
    "falling market", "price falling",
    "imbalanced (bearish)", "trending down", "price moving down",
    "aggressive selling", "put options trending",
    "bearish pressure", "bearish. ",
]
_FLAT_KEYWORDS = [
    "walk away", "stay flat", "bank profit", "stop trading",
    "reduce size", "take profit", "exit long", "rebalance",
    "risk management", "discipline", "we are done",
    "no short", "no long", "no trade", "no clear", "not ready",
    "setup rejected", "no significant", "balanced and rotational",
    "range-bound", "no directional", "wait for",
]
_HIGH_CONFIDENCE = ["with size", "squeeze", "asymmetrical", "full allocation", "full market protection"]
_LOW_CONFIDENCE = ["watching", "wait for", "wait for break", "wait for passive"]


def parse_entry_response(text: str) -> Dict[str, Any]:
    """Parse model output into direction, trying JSON first then keyword fallback."""
    # Try direct JSON parse
    parsed = _try_parse_json(text)
    if parsed is not None:
        return _normalize_entry_json(parsed, text)

    # Try extracting JSON from markdown code blocks (```json ... ``` or ``` ... ```)
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block_match:
        parsed = _try_parse_json(code_block_match.group(1))
        if parsed is not None:
            return _normalize_entry_json(parsed, text)

    # Fall back to keyword-based parsing
    logger.debug("JSON parse failed, falling back to keyword parser for: %s", text[:200])
    return _keyword_fallback_parse(text)


def _try_parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """Attempt to parse a string as JSON. Returns None on failure."""
    try:
        obj = json.loads(raw.strip())
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _normalize_entry_json(obj: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
    """Normalise a parsed JSON dict into the expected entry response format."""
    direction = str(obj.get("direction", "FLAT")).upper()
    if direction not in ("LONG", "SHORT", "FLAT"):
        direction = "FLAT"

    confidence = str(obj.get("confidence", "Medium")).capitalize()
    if confidence not in ("High", "Medium", "Low"):
        confidence = "Medium"

    return {
        "direction": direction,
        "rationale": obj.get("rationale", raw_text),
        "raw_output": raw_text,
        "confidence": confidence,
    }


def _keyword_fallback_parse(text: str) -> Dict[str, Any]:
    """Legacy keyword-based parser used when JSON parsing fails."""
    lower = text.lower()
    direction = None
    confidence = "Medium"

    trigger_match = _RE_TRIGGER.search(lower)
    if trigger_match:
        trigger = trigger_match.group(1).strip()
        direction = _match_direction_in_text(trigger)
        if direction:
            confidence = _extract_confidence(trigger)

    if direction is None:
        logic_match = _RE_LOGIC.search(lower)
        if logic_match:
            logic = logic_match.group(1).strip()
            if any(kw in logic for kw in ["aaa setup", "buy on dip", "short covering", "momentum continuation"]):
                direction = "LONG"
            elif any(kw in logic for kw in ["breakout failed", "buyers exhausted", "buyers are trapped", "momentum squeeze"]):
                direction = "SHORT"

    if direction is None:
        direction = _match_direction_in_text(lower)

    if direction is None:
        if any(kw in lower for kw in _FLAT_KEYWORDS):
            direction = "FLAT"

    if direction is None:
        direction = "FLAT"
        if not any(kw in lower for kw in _FLAT_KEYWORDS):
            logger.warning("Unparsed model output (defaulting FLAT): %s", text[:200])

    return {
        "direction": direction,
        "rationale": text,
        "raw_output": text,
        "confidence": confidence,
    }


def _match_direction_in_text(text: str) -> str | None:
    for kw in _TRIGGER_SHORT:
        if kw in text:
            return "SHORT"
    for kw in _TRIGGER_LONG:
        if kw in text:
            return "LONG"
    if re.search(r'\*\*long\*\*', text):
        return "LONG"
    if re.search(r'\*\*short\*\*', text):
        return "SHORT"
    return None


def _extract_confidence(trigger_text: str) -> str:
    if any(kw in trigger_text for kw in _HIGH_CONFIDENCE):
        return "High"
    if any(kw in trigger_text for kw in _LOW_CONFIDENCE):
        return "Low"
    return "Medium"


# =====================================================================
# Overseer prompt builder (extracted from LLMOverseerHandler)
# =====================================================================

class OverseerAction(BaseModel):
    """Trade management decision."""
    action: Literal["HOLD", "TIGHTEN_SL", "PARTIAL_EXIT", "FULL_EXIT", "ADD"] = "HOLD"
    new_sl_price: Optional[float] = None
    reason: str = ""


def build_overseer_prompt(
    pos_state: dict, tick: OHLC, amt_result: AMTResult,
    session_info: SessionInfo | None = None,
    footprint_candle: FootprintCandle | None = None,
    oi_analysis: dict | None = None,
) -> str:
    """Build rich context prompt for position management."""
    side = pos_state["side"]
    entry = pos_state["entry_price"]
    current = pos_state["current_price"]
    pnl_pct = pos_state["unrealized_pnl_pct"] * 100
    time_s = pos_state["time_in_trade_secs"]
    sl = pos_state["stop_loss"]
    tp = pos_state["take_profit"]

    parts = [
        f"Open {side} position from {entry:.2f}.",
        f"Current price: {current:.2f} (unrealized: {pnl_pct:+.2f}%).",
        f"Time in trade: {time_s:.0f}s.",
        f"Stop loss: {sl:.2f}, Take profit: {tp:.2f}.",
    ]

    if pos_state.get("partial_taken"):
        parts.append("Partial profit already taken.")
    if pos_state.get("trailing_active"):
        parts.append("Trailing stop is active.")

    market_state = "Trending" if amt_result.market_state == "IMBALANCED" else "Balanced"
    parts.append(f"Market state: {market_state}.")

    price = tick.close
    vah = amt_result.value_area_high
    val = amt_result.value_area_low
    poc = amt_result.poc

    if vah > 0 and val > 0:
        if price >= vah * 0.998:
            parts.append(f"Price at Value Area High ({vah:.0f}).")
        elif price <= val * 1.002:
            parts.append(f"Price at Value Area Low ({val:.0f}).")
        elif poc > 0 and abs(price - poc) / poc < 0.003:
            parts.append(f"Price at POC ({poc:.0f}).")
        else:
            parts.append(f"Price inside value area. POC={poc:.0f}, VAH={vah:.0f}, VAL={val:.0f}.")

    if tick.delta > 0:
        parts.append(f"Delta: +{tick.delta:.0f} (buyers active).")
    elif tick.delta < 0:
        parts.append(f"Delta: {tick.delta:.0f} (sellers active).")

    if amt_result.cvd_divergence == "BEARISH_DIV":
        parts.append("WARNING: CVD bearish divergence — buying pressure declining.")
    elif amt_result.cvd_divergence == "BULLISH_DIV":
        parts.append("WARNING: CVD bullish divergence — selling pressure declining.")
    elif amt_result.cvd_slope > 0.5:
        parts.append("CVD trending up. Buyers in control.")
    elif amt_result.cvd_slope < -0.5:
        parts.append("CVD trending down. Sellers in control.")

    if amt_result.aggressive_prints:
        recent = amt_result.aggressive_prints[-2:]
        for ap in recent:
            parts.append(f"Volume bubble: {ap.side} at {ap.price:.0f} ({ap.volume:.0f} vol).")

    vwap = tick.vwap if tick.vwap > 0 else 0
    if vwap > 0:
        if price > vwap * 1.001:
            parts.append(f"Price above VWAP ({vwap:.0f}). Bullish.")
        elif price < vwap * 0.999:
            parts.append(f"Price below VWAP ({vwap:.0f}). Bearish.")

    # Probability model exit signal
    if pos_state.get("exit_probability") is not None:
        ep = pos_state["exit_probability"]
        if ep > 0.5:
            parts.append(f"Exit probability model: {ep:.0%} chance of adverse move — consider exiting.")
        else:
            parts.append(f"Exit probability model: {ep:.0%} chance of adverse move — low risk.")

    # ── ENRICHMENT: Session info ─────────────────────────────────────
    if session_info is not None:
        parts.append(f"Session: {session_info.session}. Favor {session_info.favor_strategy}.")

    # ── ENRICHMENT: Profile shape from AMTResult ─────────────────────
    if amt_result.profile_shape:
        parts.append(f"Profile shape: {amt_result.profile_shape}.")

    # ── ENRICHMENT: LVN play from AMTResult ──────────────────────────
    if amt_result.lvn_play:
        lp = amt_result.lvn_play
        parts.append(
            f"LVN PLAY: {lp['direction']} at {lp['lvn_price']:.0f} "
            f"(vel {lp['velocity_ratio']:.1f}x, "
            f"rej={'Y' if lp['has_rejection'] else 'N'}, "
            f"flip={'Y' if lp['has_delta_flip'] else 'N'}) "
            f"-> target {lp['target']:.0f}."
        )

    # ── ENRICHMENT: OI analysis ──────────────────────────────────────
    if oi_analysis is not None:
        oi_interp = oi_analysis.get("interpretation", "")
        oi_pcr = oi_analysis.get("pcr", 0)
        parts.append(f"OI: {oi_interp}. PCR: {oi_pcr}.")

    # ── ENRICHMENT: Stacked imbalances from footprint ────────────────
    _fp_levels = None
    if footprint_candle is not None:
        _fp_levels = getattr(footprint_candle, 'levels', None) if not isinstance(footprint_candle, dict) else footprint_candle.get('levels')
    if _fp_levels:
        def _get(lv, key, default=None):
            return getattr(lv, key, default) if not isinstance(lv, dict) else lv.get(key, default)
        stacked_levels = [lv for lv in _fp_levels if _get(lv, 'stacked', False)]
        if stacked_levels:
            net_delta = sum(_get(lv, 'delta', 0) for lv in stacked_levels)
            direction = "buy" if net_delta > 0 else "sell"
            prices = [_get(lv, 'price', 0) for lv in stacked_levels]
            price_range = f"{min(prices):.0f}-{max(prices):.0f}"
            parts.append(
                f"Stacked imbalances: {len(stacked_levels)} consecutive "
                f"{direction} imbalances at {price_range}."
            )

    narrative = " ".join(parts)

    # Instruct the model to respond with structured JSON
    json_instruction = (
        "\n\nRespond ONLY with a JSON object in the following format, no extra text:\n"
        '{"action": "HOLD" | "TIGHTEN_SL" | "PARTIAL_EXIT" | "FULL_EXIT" | "ADD", '
        '"new_sl_price": <number or null>, '
        '"reason": "<brief explanation>"}'
    )

    return narrative + json_instruction


# =====================================================================
# Overseer response parser
# =====================================================================

_RE_ACTION = re.compile(
    r'action:\s*(hold|tighten\s*sl|partial\s*exit|full\s*exit|add)(?:\s+(\d+[\d.]*))?\s*',
    re.IGNORECASE,
)
_RE_REASON = re.compile(r'reason:\s*(.+?)(?:\n|$)', re.IGNORECASE)


def parse_overseer_response(text: str, pos_state: dict) -> OverseerAction:
    """Parse overseer LLM output, trying JSON first then keyword fallback."""
    # Try direct JSON parse
    parsed = _try_parse_json(text)
    if parsed is not None:
        return _normalize_overseer_json(parsed, pos_state)

    # Try extracting JSON from markdown code blocks
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_block_match:
        parsed = _try_parse_json(code_block_match.group(1))
        if parsed is not None:
            return _normalize_overseer_json(parsed, pos_state)

    # Fall back to keyword-based parsing
    logger.debug("JSON parse failed for overseer, falling back to keyword parser: %s", text[:200])
    return _keyword_fallback_parse_overseer(text, pos_state)


_VALID_OVERSEER_ACTIONS = {"HOLD", "TIGHTEN_SL", "PARTIAL_EXIT", "FULL_EXIT", "ADD"}


def _normalize_overseer_json(obj: Dict[str, Any], pos_state: dict) -> OverseerAction:
    """Normalise a parsed JSON dict into an OverseerAction."""
    action = str(obj.get("action", "HOLD")).upper().replace(" ", "_")
    if action not in _VALID_OVERSEER_ACTIONS:
        action = "HOLD"

    reason = str(obj.get("reason", ""))
    new_sl = obj.get("new_sl_price")

    # Ensure TIGHTEN_SL has a valid stop-loss price
    if action == "TIGHTEN_SL":
        if not isinstance(new_sl, (int, float)) or new_sl <= 0:
            new_sl = compute_tighten_sl(pos_state)

    return OverseerAction(
        action=action,
        new_sl_price=float(new_sl) if isinstance(new_sl, (int, float)) and new_sl and new_sl > 0 else None,
        reason=reason,
    )


def _keyword_fallback_parse_overseer(text: str, pos_state: dict) -> OverseerAction:
    """Legacy keyword-based overseer parser used when JSON parsing fails."""
    lower = text.lower()
    reason = ""

    reason_match = _RE_REASON.search(text)
    if reason_match:
        reason = reason_match.group(1).strip()

    action_match = _RE_ACTION.search(lower)
    if action_match:
        action_raw = action_match.group(1).strip()
        price_str = action_match.group(2)

        if "hold" in action_raw:
            return OverseerAction(action="HOLD", reason=reason)
        elif "tighten" in action_raw:
            new_sl = None
            if price_str:
                try:
                    new_sl = float(price_str)
                except ValueError:
                    pass
            if not new_sl or new_sl <= 0:
                new_sl = compute_tighten_sl(pos_state)
            return OverseerAction(action="TIGHTEN_SL", new_sl_price=new_sl, reason=reason)
        elif "partial" in action_raw:
            return OverseerAction(action="PARTIAL_EXIT", reason=reason)
        elif "full" in action_raw:
            return OverseerAction(action="FULL_EXIT", reason=reason)
        elif "add" in action_raw:
            return OverseerAction(action="ADD", reason=reason)

    if "full exit" in lower or "close position" in lower or "exit now" in lower:
        return OverseerAction(action="FULL_EXIT", reason=reason or "keyword match")
    if "partial" in lower and ("exit" in lower or "profit" in lower):
        return OverseerAction(action="PARTIAL_EXIT", reason=reason or "keyword match")
    if "tighten" in lower or "move stop" in lower or "breakeven" in lower:
        new_sl = compute_tighten_sl(pos_state)
        return OverseerAction(action="TIGHTEN_SL", new_sl_price=new_sl, reason=reason or "keyword match")
    if "add" in lower and ("position" in lower or "pyramid" in lower):
        return OverseerAction(action="ADD", reason=reason or "keyword match")

    if not reason:
        reason = "No clear action parsed — defaulting to hold"
    return OverseerAction(action="HOLD", reason=reason)


def compute_tighten_sl(pos_state: dict) -> float:
    """Compute a sensible tightened SL when LLM doesn't specify a price."""
    current = pos_state["current_price"]
    sl = pos_state["stop_loss"]
    if pos_state["side"] == "LONG":
        return max((sl + current) / 2, sl)
    else:
        return min((sl + current) / 2, sl)
