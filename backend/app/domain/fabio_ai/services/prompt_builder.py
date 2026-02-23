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
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


# =====================================================================
# Entry prompt builder (extracted from GenerativeAIService._build_prompt)
# =====================================================================

def build_entry_prompt(data: Dict[str, Any]) -> str:
    """Convert structured market data into the concise narrative format
    the model was fine-tuned on."""
    price = data.get("ltp", 0)
    vah = data.get("vah", 0)
    val = data.get("val", 0)
    poc = data.get("poc", 0)
    delta = data.get("delta", 0)
    market_state = data.get("market_state", "Balanced")

    parts: list[str] = []
    delta_int = int(round(delta))
    volume = data.get("volume", 0)

    # Delta significance: only call it "aggressive" if delta/volume ratio > 15%
    delta_ratio = abs(delta) / volume if volume > 0 else 0
    is_aggressive = delta_ratio > 0.15

    if val > 0 and price > 0:
        if price <= val * 1.002:
            if delta_int < 0 and is_aggressive:
                parts.append(f"VAL test at {val:.0f}. Aggressive selling with {delta_int} Delta.")
            elif delta_int < 0:
                parts.append(f"Price at VAL {val:.0f}. Delta {delta_int} (weak selling, not aggressive).")
            else:
                parts.append(f"Price at VAL {val:.0f} with +{delta_int} Delta. Buyers defending.")
        elif price >= vah * 0.998:
            if delta_int > 0 and is_aggressive:
                parts.append(f"Price broke above Value Area High {vah:.0f} with strong +{delta_int} Delta.")
            elif delta_int > 0:
                parts.append(f"Price at VAH {vah:.0f}. Delta +{delta_int} (not aggressive).")
            else:
                parts.append(f"Failed breakout above {vah:.0f}. Delta turned to {delta_int}.")
        elif poc > 0 and abs(price - poc) / poc < 0.003:
            if delta_int > 0 and is_aggressive:
                parts.append(f"At POC {poc:.0f}, delta is +{delta_int}. Buyers stepping in.")
            elif delta_int < 0 and is_aggressive:
                parts.append(f"Price at POC {poc:.0f} with aggressive sellers. Delta {delta_int}.")
            else:
                parts.append(f"Price at POC {poc:.0f}. Delta {delta_int:+d} (neutral, no aggression).")
        else:
            if "Balanced" in str(market_state):
                parts.append(f"Market is rotational. Price at {price:.0f}.")
            else:
                parts.append(f"Price at {price:.0f}. Market trending outside value area.")
            if delta_int > 0 and is_aggressive:
                parts.append(f"Aggressive buyers with +{delta_int} Delta.")
            elif delta_int < 0 and is_aggressive:
                parts.append(f"Aggressive sellers pushing. Delta {delta_int}.")
            elif delta_int != 0:
                parts.append(f"Delta {delta_int:+d} (low conviction, not aggressive).")
    else:
        parts.append(f"Price at {price:.0f}. Delta {delta_int:+d}.")

    profile_shape = data.get("profile_shape", "")
    if profile_shape and "p-shape" in profile_shape.lower():
        parts.append("A 'P-Shape' profile is forming. Long liquidation visible — sellers in control.")
    elif profile_shape and "b-shape" in profile_shape.lower():
        parts.append("A 'b-Shape' profile is forming. Short covering — buyers absorbing at lows.")
    elif profile_shape and "d-shape" in profile_shape.lower():
        parts.append("D-shaped profile. Market is balanced and rotational.")

    volume_bubbles = data.get("volume_bubbles", "")
    if volume_bubbles:
        parts.append(f"Volume bubbles detected: {volume_bubbles}.")
    else:
        parts.append("No significant volume bubbles.")

    hvns = data.get("hvns", ())
    if hvns:
        hvn_str = ", ".join(f"{h:.0f}" for h in hvns[:3])
        parts.append(f"Key HVN levels: {hvn_str}.")

    lvns = data.get("lvns", ())
    if lvns:
        lvn_str = ", ".join(f"{l:.0f}" for l in lvns[:3])
        parts.append(f"Low Volume Nodes (LVN): {lvn_str}. Price moves quickly through these levels.")

    cvd_div = data.get("cvd_divergence", "")
    cvd_slope = data.get("cvd_slope", 0.0)
    if cvd_div == "BEARISH_DIV":
        parts.append("CVD divergence: price rising but buying pressure declining. Caution for longs.")
    elif cvd_div == "BULLISH_DIV":
        parts.append("CVD divergence: price falling but selling pressure declining. Accumulation possible.")
    elif cvd_slope > 0.5:
        parts.append("CVD trending up. Buyers in control.")
    elif cvd_slope < -0.5:
        parts.append("CVD trending down. Sellers in control.")

    leg_poc = data.get("leg_poc", 0)
    leg_lvns = data.get("leg_lvns", ())
    if leg_poc > 0:
        parts.append(f"Displacement leg active. Leg POC: {leg_poc:.0f}.")
        if leg_lvns:
            parts.append(f"Leg LVNs (pullback entry zones): {', '.join(f'{l:.0f}' for l in leg_lvns[:3])}.")

    vwap = data.get("vwap", 0)
    if vwap > 0 and price > 0:
        if price > vwap * 1.001:
            parts.append(f"Price above VWAP ({vwap:.0f}). Bullish bias.")
        elif price < vwap * 0.999:
            parts.append(f"Price below VWAP ({vwap:.0f}). Bearish bias.")
        else:
            parts.append(f"Price at VWAP ({vwap:.0f}). Neutral.")

    # OI context (OI walls + PCR)
    oi_pcr = data.get("oi_pcr", 0)
    oi_sentiment = data.get("oi_sentiment", "")
    oi_nearest_support = data.get("oi_nearest_support", 0)
    oi_nearest_resistance = data.get("oi_nearest_resistance", 0)
    if oi_pcr > 0:
        if oi_sentiment:
            parts.append(f"PCR: {oi_pcr:.2f} ({oi_sentiment}).")
        if oi_nearest_support > 0:
            parts.append(f"OI support wall at {oi_nearest_support:.0f}.")
        if oi_nearest_resistance > 0:
            parts.append(f"OI resistance wall at {oi_nearest_resistance:.0f}.")

    # Opening relation (gap analysis from prior session VA)
    opening_relation = data.get("opening_relation", "")
    if opening_relation and opening_relation != "IN_BALANCE":
        if opening_relation == "OUT_ABOVE":
            parts.append("Gap-up open above prior VA — bullish initiative, favor trend continuation.")
        elif opening_relation == "OUT_BELOW":
            parts.append("Gap-down open below prior VA — bearish initiative, favor trend continuation.")

    # Strategy hint — tells model whether to favor mean reversion or trend
    strategy_hint = data.get("strategy_hint", "")
    if strategy_hint:
        parts.append(strategy_hint)

    narrative = " ".join(parts)

    # Instruct the model to respond with structured JSON
    json_instruction = (
        "\n\nRespond ONLY with a JSON object in the following format, no extra text:\n"
        '{"direction": "LONG" | "SHORT" | "FLAT", '
        '"rationale": "<brief explanation>", '
        '"confidence": "High" | "Medium" | "Low", '
        '"market_state": "<current market state>"}'
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
]
_TRIGGER_SHORT = [
    "enter short", "short on confirmation", "short with target",
    "short or", "short with", "short on rotation", "short with size",
    "buyers exhausted", "buyers are trapped", "failed breakout",
    "bearish bias", "sellers in control", "bearish momentum", "sell signal",
    "short entry", "favor short", "favour short", "go short", "bearish trend",
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
