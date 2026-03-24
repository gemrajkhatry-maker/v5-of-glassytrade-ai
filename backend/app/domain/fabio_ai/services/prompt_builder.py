"""Pure prompt construction and response parsing for LLM entry and overseer.

All functions are stateless and side-effect-free — no I/O, no threading.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from pydantic import BaseModel
from app.domain.fabio_ai.services.llm_contract import entry_response_schema_instruction
from app.domain.trading.models.enums import MarketStateCodec, ProfileShapeCodec

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, FootprintCandle
    from app.domain.fabio_ai.services.session_context import SessionInfo

logger = logging.getLogger(__name__)

OVERSEER_INSTRUCTION = (
    "You are an active trade manager following Fabio Valentini's orderflow methodology. "
    "You are managing an open position. Analyze the current market data and position state. "
    "Respond with a single JSON object containing 'action' and 'reason'.\n"
    "Valid actions: HOLD, TIGHTEN_SL, PARTIAL_EXIT, FULL_EXIT, ADD.\n"
    "If TIGHTEN_SL, also include 'new_sl_price'.\n"
    'Example: {"action": "HOLD", "reason": "conviction unchanged"}'
)


class OverseerAction(BaseModel):
    """Trade management decision."""

    action: Literal["HOLD", "TIGHTEN_SL", "PARTIAL_EXIT", "FULL_EXIT", "ADD"] = "HOLD"
    new_sl_price: Optional[float] = None
    reason: str = ""


# =====================================================================
# Shared Narrative Logic
# =====================================================================


def _build_core_amt_narrative(data: Dict[str, Any]) -> str:
    """Core logic to build Fabio Valentini's AMT narrative.

    NOW ALIGNED WITH FABIO'S THINKING PROCESS:
    1. Market State (balanced vs imbalanced → active model)
    2. Location (VAH/VAL/POC/LVN → entry zones)
    3. Aggression (CVD, delta, big orders → confirmation)

    Shared by both entry and overseer prompts to ensure context parity.
    """
    price = data.get("ltp", 0)
    vah = data.get("vah", 0)
    val = data.get("val", 0)
    poc = data.get("poc", 0)
    delta = data.get("delta", 0)
    volume = data.get("volume", 0)
    market_state = data.get("market_state", "BALANCED")
    is_balanced = MarketStateCodec.is_balanced(market_state)

    parts: list[str] = []

    # ── §1 SESSION CONTEXT (Fabio: timing matters) ──────────────────
    session_name = data.get("session_name", "")
    favor_strategy = data.get("favor_strategy", "")
    if session_name:
        parts.append(f"SESSION: {session_name}.")
    if favor_strategy and favor_strategy != "NEUTRAL":
        active_model = (
            "TREND CONTINUATION"
            if favor_strategy == "TREND_CONTINUATION"
            else "MEAN REVERSION"
        )
        parts.append(f"Session favors: {active_model}.")

    prior_poc = data.get("prior_poc", 0)
    prior_vah = data.get("prior_vah", 0)
    prior_val = data.get("prior_val", 0)
    if prior_poc > 0 and prior_vah > 0 and prior_val > 0:
        parts.append(
            f"PRIOR SESSION: POC {prior_poc:.0f}, VAH {prior_vah:.0f}, VAL {prior_val:.0f}."
        )
    else:
        parts.append(
            "PRIOR SESSION: No historical data — using current session VA only."
        )

    gap_type = data.get("gap_type", "")
    opening_bias = data.get("opening_bias", "")
    if gap_type:
        parts.append(f"Gap: {gap_type}.")
    if opening_bias and opening_bias not in ("NEUTRAL", "IN_BALANCE"):
        parts.append(f"Opening bias: {opening_bias}.")

    ib_high = data.get("ib_high", 0)
    ib_low = data.get("ib_low", 0)
    ib_complete = data.get("ib_complete", False)
    if ib_high > 0 and ib_low > 0 and ib_high != ib_low:
        status = "complete" if ib_complete else "forming"
        ib_range = ib_high - ib_low
        parts.append(
            f"IB ({status}): {ib_low:.2f}-{ib_high:.2f} (range: {ib_range:.2f})."
        )
    elif ib_high > 0 and ib_low > 0:
        # FIX: IB showing zero range — show as forming
        parts.append(f"IB (forming): {ib_low:.2f}-{ib_high:.2f} — range expanding")

    # ── §2 MARKET STATE (Fabio: Step 1 — Balance vs Imbalance) ──────
    if is_balanced:
        parts.append("MARKET STATE: BALANCED. Active model: MEAN REVERSION.")
        parts.append("Seek: Failed breakout → snap back to POC.")
    else:
        parts.append("MARKET STATE: IMBALANCED. Active model: TREND CONTINUATION.")
        parts.append("Seek: Pullback to LVN → continuation.")

    # FIX: Show price distance from VA for context
    if vah > 0 and val > 0 and price > 0:
        va_width = vah - val
        if va_width > 0:
            if price > vah:
                pct_above = ((price - vah) / va_width) * 100
                parts.append(
                    f"⚠️ Price +{price - vah:.2f} ABOVE VAH (+{pct_above:.0f}% of VA width) — breakout zone"
                )
            elif price < val:
                pct_below = ((val - price) / va_width) * 100
                parts.append(
                    f"⚠️ Price {price - val:.2f} BELOW VAL (-{pct_below:.0f}% of VA width) — breakdown zone"
                )
            else:
                pos_in_va = ((price - val) / va_width) * 100
                parts.append(f"Price inside VA ({pos_in_va:.0f}% from VAL to VAH)")

    acceptance_above = data.get("acceptance_above", False)
    acceptance_below = data.get("acceptance_below", False)
    rejection_high = data.get("rejection_at_high", False)
    rejection_low = data.get("rejection_at_low", False)

    if acceptance_above:
        parts.append("ACCEPTANCE above VAH.")
    if acceptance_below:
        parts.append("ACCEPTANCE below VAL.")
    if rejection_high:
        parts.append("REJECTION at VAH.")
    if rejection_low:
        parts.append("REJECTION at VAL.")

    mkt_struct = data.get("market_structure", "")
    if mkt_struct and mkt_struct != "BALANCE":
        parts.append(f"Structure: {mkt_struct}.")

    # Profile shape warnings (CRITICAL for direction blocking)
    _ps = ProfileShapeCodec.normalize(data.get("profile_shape", "D"))
    if _ps == "P":
        parts.append("⚠️ P-SHAPE: Sellers distributing. DO NOT GO LONG.")
    elif _ps == "b":
        parts.append("⚠️ b-SHAPE: Buyers absorbing. DO NOT GO SHORT.")
    elif _ps == "B":
        parts.append("B-shape: bimodal — both sides active, potential breakout.")
    elif _ps == "D":
        parts.append("D-shape: balanced rotation.")

    # ── §3 PRICE LOCATION (Fabio: Step 2 — LVN/VA levels) ──────────
    if val > 0 and price > 0:
        if price <= val * 1.002:
            parts.append(f"LOCATION: Price at VAL ({val:.0f}). Entry zone for LONG.")
        elif price >= vah * 0.998:
            parts.append(f"LOCATION: Price at VAH ({vah:.0f}). Entry zone for SHORT.")
        elif poc > 0 and abs(price - poc) / poc < 0.003:
            parts.append(
                f"LOCATION: Price at POC ({poc:.0f}). Fair value — WAIT for bias."
            )
        else:
            parts.append(
                f"LOCATION: Price {price:.0f}. POC={poc:.0f}, VAH={vah:.0f}, VAL={val:.0f}."
            )

    # LVN levels (Fabio's reaction zones)
    lvns = data.get("lvns", [])
    if lvns:
        lvn_str = ", ".join(f"{l:.0f}" for l in lvns[:3])
        parts.append(f"LVNs: {lvn_str}. These are reaction zones on pullback.")

    # Stacked imbalances (from footprint)
    stacked_imbalances = data.get("stacked_imbalances", "")
    if stacked_imbalances:
        parts.append(f"Stacked imbalances: {stacked_imbalances}.")

    # Developing VA
    dev_poc = data.get("dev_poc", 0)
    dev_vah = data.get("dev_vah", 0)
    dev_val = data.get("dev_val", 0)
    if dev_poc > 0 and (dev_poc != poc or dev_vah != vah):
        parts.append(
            f"Developing VA: POC {dev_poc:.0f}, VAH {dev_vah:.0f}, VAL {dev_val:.0f}."
        )

    # Impulse leg levels
    leg_poc = data.get("leg_poc", 0)
    if leg_poc > 0:
        leg_vah = data.get("leg_vah", 0)
        leg_val = data.get("leg_val", 0)
        parts.append(
            f"Impulse leg: POC {leg_poc:.0f}, VAH {leg_vah:.0f}, VAL {leg_val:.0f}."
        )

    # Second drive (CRITICAL: Fabio's #1 filter)
    if data.get("is_second_drive", False):
        parts.append(
            "✅ SECOND DRIVE: High probability re-test setup. CONFIDENCE HIGH."
        )
    else:
        parts.append("⚠️ FIRST DRIVE: Lower probability. Wait for re-test if possible.")

    # LVN Play (highest conviction)
    lvn_play = data.get("lvn_play")
    if lvn_play:
        if isinstance(lvn_play, dict):
            direction = lvn_play.get("direction", "")
            level = lvn_play.get("level", 0)
            confluence = lvn_play.get("confluence", "")
            parts.append(
                f"🎯 LVN PLAY: {direction} at {level:.0f} ({confluence}). HIGH CONVICTION."
            )
        else:
            parts.append(f"🎯 LVN PLAY: {lvn_play}.")

    # ── §4 ORDER FLOW (Fabio: Step 3 — Aggression confirmation) ────
    # CVD slope
    cvd_raw = data.get("cvd", data.get("cvd_slope", 0))
    try:
        cvd_val = float(cvd_raw)
    except (ValueError, TypeError):
        cvd_val = 0.0

    if abs(cvd_val) > 100:
        if cvd_val < -100:
            parts.append(
                f"🚨 CVD EXTREME SELLING ({cvd_val:.0f}). DO NOT FADE — heavy institutional pressure."
            )
        else:
            parts.append(
                f"🚨 CVD EXTREME BUYING (+{cvd_val:.0f}). DO NOT FADE — heavy institutional pressure."
            )
    elif cvd_val > 0.5:
        parts.append(f"CVD: Sustained buying ({cvd_val:+.1f}).")
    elif cvd_val < -0.5:
        parts.append(f"CVD: Sustained selling ({cvd_val:+.1f}).")

    # CVD divergence
    cvd_div = data.get("cvd_divergence", "")
    if cvd_div == "BEARISH_DIV":
        parts.append("⚠️ CVD DIVERGENCE: Bearish. DO NOT GO LONG.")
    elif cvd_div == "BULLISH_DIV":
        parts.append("⚠️ CVD DIVERGENCE: Bullish. DO NOT GO SHORT.")

    # Delta
    if delta == 0:
        parts.append("Delta: +0 (no aggression signal).")
    else:
        parts.append(f"Delta: {delta:+.0f}.")

    # Aggression status
    aggression = data.get("aggression", "NEUTRAL")
    if aggression == "AGGRESSIVE":
        parts.append("AGGRESSION: Confirmed. Entry trigger present.")
    else:
        parts.append("AGGRESSION: Weak. Higher risk — wait for confirmation.")

    # Aggressive prints (institutional orders)
    aggressive_prints = data.get("aggressive_prints", [])
    if aggressive_prints:
        for ap in aggressive_prints[-2:]:
            if isinstance(ap, dict):
                parts.append(
                    f"Big order: {ap.get('side', '?')} at {ap.get('price', 0):.0f}."
                )

    # Volume bubbles (institutional volume spikes)
    volume_bubbles = data.get("volume_bubbles", "")
    if volume_bubbles:
        parts.append(f"Volume bubbles: {volume_bubbles}")

    # Bubble retests
    bubble_retests = data.get("bubble_retests", [])
    if bubble_retests:
        for br in bubble_retests:
            side = (
                getattr(br, "side", br.get("side", ""))
                if isinstance(br, dict)
                else getattr(br, "side", "")
            )
            price_val = (
                getattr(br, "price", br.get("price", 0))
                if isinstance(br, dict)
                else getattr(br, "price", 0)
            )
            if price_val > 0:
                parts.append(
                    f"BUBBLE RE-TEST: High volume {side} area at {price_val:.0f} being re-tested."
                )

    # ── §5 VWAP CONTEXT ────────────────────────────────────────────
    session_vwap = data.get("session_vwap", 0)
    if session_vwap > 0 and price > 0:
        if price > session_vwap:
            parts.append(f"VWAP: Price above VWAP ({session_vwap:.0f}). Bullish bias.")
        else:
            parts.append(f"VWAP: Price below VWAP ({session_vwap:.0f}). Bearish bias.")

        vwap_upper_2 = data.get("vwap_upper_2", 0)
        vwap_lower_2 = data.get("vwap_lower_2", 0)
        if vwap_upper_2 > 0 and price >= vwap_upper_2:
            parts.append("⚠️ At VWAP +2σ: Overextended.")
        elif vwap_lower_2 > 0 and price <= vwap_lower_2:
            parts.append("⚠️ At VWAP -2σ: Overextended.")

    # ── §6 WARNINGS (Inform LLM, don't block) ────────────────────
    warnings = []
    if data.get("aggression_warning"):
        warnings.append(f"⚠️ {data['aggression_warning']}")
    if data.get("drive_warning"):
        warnings.append(f"⚠️ {data['drive_warning']}")
    if data.get("cvd_warning"):
        warnings.append(f"⚠️ {data['cvd_warning']}")
    if warnings:
        parts.append("CONSIDERATIONS: " + " ".join(warnings))

    # ── §7 ORDER BOOK LIQUIDITY (NSE depth20 / MCX 5-level) ──────────
    ob_obi = data.get("obi", None)
    if ob_obi is not None:
        if ob_obi > 0.3:
            parts.append(f"ORDER BOOK: Strong bid support (OBI={ob_obi:.2f})")
        elif ob_obi < -0.3:
            parts.append(f"ORDER BOOK: Strong ask pressure (OBI={ob_obi:.2f})")
        else:
            parts.append(f"ORDER BOOK: Balanced (OBI={ob_obi:.2f})")

    bid_walls = data.get("bid_walls", "")
    if bid_walls:
        parts.append(f"BID WALLS: {bid_walls}")

    ask_walls = data.get("ask_walls", "")
    if ask_walls:
        parts.append(f"ASK WALLS: {ask_walls}")

    absorption = data.get("absorption_side", "")
    if absorption:
        parts.append(f"ABSORPTION: {absorption}")

    # ── §8 QUANT ENGINE PROBABILITY ─────────────────────────────────
    # Embed the LightGBM first-passage probability so the LLM can reference it.
    # This bridges the Monitor panel P with the Probability panel P.
    ml_signal = data.get("ml_signal")
    if ml_signal and isinstance(ml_signal, dict):
        qdir = ml_signal.get("direction", "")
        qprob = ml_signal.get("probability", 0.0)
        qregime = ml_signal.get("regime", "")
        if qdir and qprob > 0:
            parts.append(
                f"QUANT ENGINE: direction={qdir} P={qprob:.3f} regime={qregime}. "
                f"This is the statistical model's estimate — consider it alongside your AMT analysis."
            )

    # ── §9 FABIO'S CORE RULES ──────────────────────────────────────
    parts.append(
        "FABIO RULES: "
        "1) READ the market — State + Location + Aggression. "
        "2) SECOND DRIVE has higher probability than first. "
        "3) Target = POC for reversion, extended VA for trend. "
        "4) If wrong, be wrong IMMEDIATELY. Never widen stop. "
        "5) Respect institutional pressure (CVD extremes). "
        "6) Profile shape: P-shape = avoid LONG, b-shape = avoid SHORT."
    )

    return " ".join(parts)


# =====================================================================
# Prompt Builders
# =====================================================================


def build_entry_prompt(data: Dict[str, Any], allow_short: bool = False) -> str:
    """Build entry prompt using the core AMT narrative."""
    narrative = _build_core_amt_narrative(data)

    # Add option-specific context for entry
    opt_parts = []
    iv = data.get("iv", 0)
    theta = data.get("theta", 0)
    if iv > 0:
        opt_parts.append(f"IV: {iv:.1%}. Theta: {theta:.1f}/day.")

    final_prompt = narrative
    if opt_parts:
        final_prompt += " " + " ".join(opt_parts)

    # Legacy tests expect "Respond ONLY with a JSON object" explicitly if they match that exact string
    # We add it here to ensure compatibility while keeping the schema instruction
    return (
        final_prompt
        + "\n\nRespond ONLY with a JSON object in the following format:\n"
        + entry_response_schema_instruction(allow_short=allow_short)
    )


def build_overseer_prompt(
    pos_state: dict,
    tick: OHLC,
    amt_result: AMTResult,
    session_info: Optional[SessionInfo] = None,
    footprint_candle: Optional[FootprintCandle] = None,
) -> str:
    """Build rich context prompt for position management."""

    # Map objects to core dict
    # Safely handle attributes that might be missing or MagicMocks
    def _safe_float(obj, attr, default=0.0):
        val = getattr(obj, attr, default)
        try:
            return float(val)
        except:
            return default

    core_data = {
        "ltp": _safe_float(tick, "close"),
        "vah": getattr(amt_result, "value_area_high", getattr(amt_result, "vah", 0.0)),
        "val": getattr(amt_result, "value_area_low", getattr(amt_result, "val", 0.0)),
        "poc": _safe_float(amt_result, "poc"),
        "delta": _safe_float(tick, "delta"),
        "volume": _safe_float(tick, "volume"),
        "cvd": getattr(amt_result, "cvd", getattr(amt_result, "cvd_slope", 0.0)),
        "cvd_divergence": getattr(amt_result, "cvd_divergence", ""),
        "market_state": getattr(amt_result, "market_state", "Balanced"),
        "profile_shape": getattr(amt_result, "profile_shape", ""),
        "is_second_drive": getattr(amt_result, "is_second_drive", False),
        "market_structure": getattr(amt_result, "market_structure_state", ""),
        "aggressive_prints": [
            {"side": ap.side, "price": ap.price} for ap in amt_result.aggressive_prints
        ]
        if hasattr(amt_result, "aggressive_prints") and amt_result.aggressive_prints
        else [],
        "bubble_retests": [
            {"side": ap.side, "price": ap.price}
            for ap in getattr(amt_result, "bubble_retests", [])
        ],
        "lvn_play": getattr(amt_result, "lvn_play", None),
    }

    if session_info:
        core_data.update(
            {
                "gap_type": getattr(session_info, "gap_type", ""),
                "opening_bias": getattr(session_info, "opening_inventory_bias", ""),
                "ib_high": _safe_float(session_info, "ib_high"),
                "ib_low": _safe_float(session_info, "ib_low"),
            }
        )
        # Add session info if it doesn't fit core narrative perfectly
        core_data["session_name"] = getattr(session_info, "session", "")
        core_data["favor_strategy"] = getattr(session_info, "favor_strategy", "")

    if footprint_candle:
        # Check for stacked imbalances
        levels = getattr(footprint_candle, "levels", [])
        stacked = [lv for lv in levels if getattr(lv, "stacked", False)]
        if stacked:
            core_data["stacked_imbalances"] = f"{len(stacked)} levels"

    # Core narrative
    narrative = _build_core_amt_narrative(core_data)

    # Extra session context not covered by core
    if session_info:
        sess_line = f"Session: {core_data['session_name']}. Favor {core_data['favor_strategy']}."
        narrative = sess_line + " " + narrative

    # Position state enrichment
    pos_parts = [
        f"Open {pos_state['side']} position from {pos_state['entry_price']:.2f}.",
        f"Current price: {pos_state['current_price']:.2f} (unrealized: {pos_state['unrealized_pnl_pct'] * 100:+.2f}%).",
        f"Stop loss: {pos_state['stop_loss']:.2f}, Take profit: {pos_state['take_profit']:.2f}.",
    ]

    final_prompt = " ".join(pos_parts) + " " + narrative

    # Overseer instruction
    return final_prompt + "\n\n" + OVERSEER_INSTRUCTION


# =====================================================================
# Parsers
# =====================================================================


def parse_entry_response(text: str) -> Dict[str, Any]:
    """Parse model output into direction, trying JSON first then keyword fallback."""
    parsed = _try_parse_json(text)
    if parsed is not None:
        return _normalize_entry_json(parsed, text)

    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block_match:
        parsed = _try_parse_json(code_block_match.group(1))
        if parsed is not None:
            return _normalize_entry_json(parsed, text)

    # Legacy structured extraction as fallback
    structured = _try_structured_parse(text)
    if structured is not None:
        return structured

    logger.warning(
        "Unparsed model output — falling back to keyword parser: %.120s", text
    )
    return _keyword_fallback_parse(text)


def parse_overseer_response(text: str, pos_state: dict) -> OverseerAction:
    """Parse overseer LLM output, trying JSON first then keyword fallback."""
    parsed = _try_parse_json(text)
    if parsed is not None:
        return _normalize_overseer_json(parsed, pos_state)

    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block_match:
        parsed = _try_parse_json(code_block_match.group(1))
        if parsed is not None:
            return _normalize_overseer_json(parsed, pos_state)

    return _keyword_fallback_parse_overseer(text, pos_state)


def _try_parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """Attempt to parse a string as JSON. Returns None on failure.

    IMPROVED: Attempts to fix common LLM JSON formatting issues before parsing.
    """
    text = raw.strip()
    if not text:
        return None

    # Try direct parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except:
        pass

    # Extract JSON block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        json_text = match.group(0)

        # Try direct parse of extracted block
        try:
            obj = json.loads(json_text)
            if isinstance(obj, dict):
                return obj
        except:
            pass

        # FIX #1: Unquoted keys (LLM often outputs "Key": instead of "Key":)
        # Pattern: word followed by colon but not quoted
        json_text = re.sub(r"(?<=[{,])\s*(\w+)\s*:", r' "\1":', json_text)

        # FIX #2: Single quotes to double quotes
        json_text = json_text.replace("'", '"')

        # FIX #3: Remove trailing commas before } or ]
        json_text = re.sub(r",\s*([}\]])", r"\1", json_text)

        # FIX #4: Handle missing closing quotes in values
        # Pattern: ": value without closing quote before comma or }
        json_text = re.sub(r':\s*"([^"]*?)(?=[,}\n])', r': "\1"', json_text)

        try:
            obj = json.loads(json_text)
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            # Last resort: try to extract key-value pairs manually
            pass

    return None


def _normalize_entry_json(obj: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
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


def _normalize_overseer_json(obj: Dict[str, Any], pos_state: dict) -> OverseerAction:
    action = str(obj.get("action", "HOLD")).upper().replace(" ", "_")
    if action not in {"HOLD", "TIGHTEN_SL", "PARTIAL_EXIT", "FULL_EXIT", "ADD"}:
        action = "HOLD"
    new_sl = obj.get("new_sl_price")
    if action == "TIGHTEN_SL" and (not isinstance(new_sl, (int, float)) or new_sl <= 0):
        new_sl = compute_tighten_sl(pos_state)
    return OverseerAction(
        action=action,
        new_sl_price=float(new_sl)
        if isinstance(new_sl, (int, float)) and new_sl > 0
        else None,
        reason=str(obj.get("reason", "")),
    )


def _try_structured_parse(text: str) -> Optional[Dict[str, Any]]:
    trigger_match = re.search(r"trigger:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if not trigger_match:
        return None
    trigger_text = trigger_match.group(1).strip().lower()
    direction = (
        "LONG"
        if "long" in trigger_text
        else "SHORT"
        if "short" in trigger_text
        else "FLAT"
    )
    confidence = (
        "High" if "size" in trigger_text or "full" in trigger_text else "Medium"
    )
    logic_match = re.search(
        r"logic:\s*(.+?)(?:\n|trigger)", text, re.IGNORECASE | re.DOTALL
    )
    rationale = logic_match.group(1).strip() if logic_match else text
    return {
        "direction": direction,
        "rationale": rationale,
        "raw_output": text,
        "confidence": confidence,
    }


def _keyword_fallback_parse(text: str) -> Dict[str, Any]:
    lower = text.lower()

    # Logic fallback first (matches legacy tests)
    if any(
        kw in lower
        for kw in ["aaa setup", "buy on dip", "short covering", "momentum continuation"]
    ):
        return {
            "direction": "LONG",
            "rationale": text,
            "raw_output": text,
            "confidence": "Medium",
        }
    if any(
        kw in lower
        for kw in [
            "breakout failed",
            "buyers exhausted",
            "buyers are trapped",
            "momentum squeeze",
        ]
    ):
        return {
            "direction": "SHORT",
            "rationale": text,
            "raw_output": text,
            "confidence": "Medium",
        }

    if "long" in lower:
        return {
            "direction": "LONG",
            "rationale": text,
            "raw_output": text,
            "confidence": "Medium",
        }
    if "short" in lower:
        return {
            "direction": "SHORT",
            "rationale": text,
            "raw_output": text,
            "confidence": "Medium",
        }
    return {
        "direction": "FLAT",
        "rationale": text,
        "raw_output": text,
        "confidence": "Medium",
    }


def _keyword_fallback_parse_overseer(text: str, pos_state: dict) -> OverseerAction:
    lower = text.lower()
    if "full exit" in lower or "close position" in lower:
        return OverseerAction(action="FULL_EXIT", reason=text)
    if "partial" in lower:
        return OverseerAction(action="PARTIAL_EXIT", reason=text)
    if "tighten" in lower:
        return OverseerAction(
            action="TIGHTEN_SL", new_sl_price=compute_tighten_sl(pos_state), reason=text
        )
    if "add" in lower:
        return OverseerAction(action="ADD", reason=text)
    return OverseerAction(action="HOLD", reason=text)


def compute_tighten_sl(pos_state: dict) -> float:
    current = pos_state["current_price"]
    sl = pos_state["stop_loss"]
    if pos_state["side"] == "LONG":
        return max((sl + current) / 2, sl)
    return min((sl + current) / 2, sl)
