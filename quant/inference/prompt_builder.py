"""Pure prompt construction and response parsing for LLM entry and overseer.

All functions are stateless and side-effect-free — no I/O, no threading.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from pydantic import BaseModel
from quant.inference.llm_contract import entry_response_schema_instruction
from quant.contracts.enums import MarketStateCodec, ProfileShapeCodec

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC, AMTResult, FootprintCandle
    # SessionInfo lives in backend session_context (not yet migrated); the type
    # hint is only used under TYPE_CHECKING so the import is intentionally absent.

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


def _build_narrative_session_context(data: Dict[str, Any]) -> list[str]:
    """#1 Session context: session name, prior data, gap, IB.

    Tolerant of a partial key set: the training dataset only provides a
    session tag, so `session_name` falls back to the live NSE default and the
    PRIOR SESSION line is skipped entirely when no prior-* keys are present
    (the live app always sends them, even as 0.0).
    """
    parts: list[str] = []
    session_name = data.get("session_name") or "NSE_PRIMARY"
    parts.append(f"SESSION: {session_name}.")
    favor_strategy = data.get("favor_strategy", "")
    if favor_strategy and favor_strategy != "NEUTRAL":
        active_model = (
            "TREND CONTINUATION"
            if favor_strategy == "TREND_CONTINUATION"
            else "MEAN REVERSION"
        )
        parts.append(f"Session favors: {active_model}.")
    if "prior_poc" in data or "prior_vah" in data or "prior_val" in data:
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
        parts.append(f"IB (forming): {ib_low:.2f}-{ib_high:.2f} — range expanding")
    return parts


def _build_narrative_market_state(data: Dict[str, Any]) -> list[str]:
    """#2 Market state, price location, LVN, VAH/VAL, profile shape."""
    parts: list[str] = []
    price = data.get("ltp", 0)
    vah = data.get("vah", 0)
    val = data.get("val", 0)
    poc = data.get("poc", 0)
    is_balanced = MarketStateCodec.is_balanced(data.get("market_state", "BALANCED"))
    if is_balanced:
        parts.append("MARKET STATE: BALANCED. Active model: MEAN REVERSION.")
        parts.append("Seek: Failed breakout → snap back to POC.")
    else:
        parts.append("MARKET STATE: IMBALANCED. Active model: TREND CONTINUATION.")
        parts.append("Seek: Pullback to LVN → continuation.")
    if (
        isinstance(vah, (int, float))
        and isinstance(val, (int, float))
        and isinstance(price, (int, float))
        and vah > 0
        and val > 0
        and price > 0
    ):
        va_width = vah - val
        if va_width > 0:
            if price > vah:
                pct = ((price - vah) / va_width) * 100
                parts.append(
                    f"⚠️ Price +{price - vah:.2f} ABOVE VAH (+{pct:.0f}% of VA width) — breakout zone"
                )
            elif price < val:
                pct = ((val - price) / va_width) * 100
                parts.append(
                    f"⚠️ Price {price - val:.2f} BELOW VAL (-{pct:.0f}% of VA width) — breakdown zone"
                )
            else:
                pos = ((price - val) / va_width) * 100
                parts.append(f"Price inside VA ({pos:.0f}% from VAL to VAH)")
    for flag, msg in [
        ("acceptance_above", "ACCEPTANCE above VAH."),
        ("acceptance_below", "ACCEPTANCE below VAL."),
        ("rejection_at_high", "REJECTION at VAH."),
        ("rejection_at_low", "REJECTION at VAL."),
    ]:
        if data.get(flag):
            parts.append(msg)
    mkt_struct = data.get("market_structure", "")
    if mkt_struct and mkt_struct != "BALANCE":
        parts.append(f"Structure: {mkt_struct}.")
    _ps = ProfileShapeCodec.normalize(data.get("profile_shape", "D"))
    shapes = {
        "P": "⚠️ P-SHAPE: Sellers distributing. DO NOT GO LONG.",
        "b": "⚠️ b-SHAPE: Buyers absorbing. DO NOT GO SHORT.",
        "B": "B-shape: bimodal — both sides active, potential breakout.",
        "D": "D-shape: balanced rotation.",
    }
    if _ps in shapes:
        parts.append(shapes[_ps])
    if isinstance(val, (int, float)) and isinstance(price, (int, float)) and val > 0 and price > 0:
        if price <= val * 1.002:
            parts.append(f"LOCATION: Price at VAL ({val:.0f}). Entry zone for LONG.")
        elif (
            isinstance(poc, (int, float))
            and isinstance(vah, (int, float))
            and poc > 0
            and abs(price - poc) / poc < 0.003
        ):
            parts.append(
                f"LOCATION: Price at POC ({poc:.0f}). Fair value — WAIT for bias."
            )
        elif isinstance(poc, (int, float)) and isinstance(vah, (int, float)):
            parts.append(
                f"LOCATION: Price {price:.0f}. POC={poc:.0f}, VAH={vah:.0f}, VAL={val:.0f}."
            )
    elif (
        isinstance(price, (int, float))
        and price > 0
        and not (
            isinstance(vah, (int, float))
            and isinstance(val, (int, float))
            and vah > 0
            and val > 0
        )
    ):
        # Dataset-only fallback: nifty_amt_data rows carry `price` but no VA
        # levels, so the location math above is skipped — still emit the price.
        # Live always sends vah/val > 0, so this branch never fires live.
        parts.append(f"LOCATION: Price {price:.0f}.")
    lvns = data.get("lvns", [])
    if lvns:
        parts.append(
            f"LVNs: {', '.join(f'{l:.0f}' for l in lvns[:3])}. Reaction zones on pullback."
        )
    stacked = data.get("stacked_imbalances", "")
    if stacked:
        parts.append(f"Stacked imbalances: {stacked}.")
    dev_poc = data.get("dev_poc", 0)
    if dev_poc > 0 and (dev_poc != poc or data.get("dev_vah", 0) != vah):
        parts.append(
            f"Developing VA: POC {dev_poc:.0f}, VAH {data.get('dev_vah', 0):.0f}, VAL {data.get('dev_val', 0):.0f}."
        )
    leg_poc = data.get("leg_poc", 0)
    if leg_poc > 0:
        parts.append(
            f"Impulse leg: POC {leg_poc:.0f}, VAH {data.get('leg_vah', 0):.0f}, VAL {data.get('leg_val', 0):.0f}."
        )
    if data.get("is_second_drive"):
        parts.append(
            "✅ SECOND DRIVE: High probability re-test setup. CONFIDENCE HIGH."
        )
    else:
        parts.append("⚠️ FIRST DRIVE: Lower probability. Wait for re-test if possible.")
    lvn_play = data.get("lvn_play")
    if lvn_play:
        if isinstance(lvn_play, dict):
            parts.append(
                f"🎯 LVN PLAY: {lvn_play.get('direction', '')} at {lvn_play.get('level', 0):.0f} ({lvn_play.get('confluence', '')}). HIGH CONVICTION."
            )
        else:
            parts.append(f"🎯 LVN PLAY: {lvn_play}.")
    session_vwap = data.get("session_vwap", 0)
    if session_vwap > 0 and price > 0:
        parts.append(
            f"VWAP: Price {'above' if price > session_vwap else 'below'} VWAP ({session_vwap:.0f}). {'Bullish' if price > session_vwap else 'Bearish'} bias."
        )
        if data.get("vwap_upper_2", 0) > 0 and price >= data["vwap_upper_2"]:
            parts.append("⚠️ At VWAP +2σ: Overextended.")
        elif data.get("vwap_lower_2", 0) > 0 and price <= data["vwap_lower_2"]:
            parts.append("⚠️ At VWAP -2σ: Overextended.")
    return parts


def _build_narrative_order_flow(data: Dict[str, Any]) -> list[str]:
    """#3 Order flow: CVD, delta, aggression, bubbles, quant engine, rules."""
    parts: list[str] = []

    # Priority 1: Aggression (CVD, Delta, OFI) - MANDATORY DESCRIPTION
    parts.append("--- ORDER FLOW & AGGRESSION ---")

    cvd_raw = data.get("cvd_slope", data.get("cvd", 0))
    aggression_score = data.get("aggression", 0)
    if aggression_score is None:
        aggression_score = 0.0
    # Ensure it's a float for formatting
    try:
        aggression_score = float(aggression_score)
    except (ValueError, TypeError):
        aggression_score = 0.0

    parts.append(f"Aggression Score: {aggression_score:.2f} (0.0 to 2.0 scale).")

    cvd_div = data.get("cvd_divergence", "")
    if cvd_div == "BEARISH_DIV":
        parts.append("⚠️ CVD DIVERGENCE: Bearish setup. DO NOT GO LONG.")
    elif cvd_div == "BULLISH_DIV":
        parts.append("⚠️ CVD DIVERGENCE: Bullish setup. DO NOT GO SHORT.")

    # CVD slope magnitude warnings (tests expect these exact texts)
    try:
        cvd_slope = float(cvd_raw)
    except (ValueError, TypeError):
        cvd_slope = 0.0

    if cvd_slope < -100:
        parts.append("CVD EXTREME SELLING. DO NOT FADE.")
    elif cvd_slope > 100:
        parts.append("CVD EXTREME BUYING. DO NOT FADE.")
    elif cvd_slope <= -3:
        parts.append("Sustained selling.")
    elif cvd_slope >= 3:
        parts.append("Sustained buying.")

    # Priority 2: Quant Probability (Soft Gate Context)
    quant_ctx = data.get("ml_signal") or data.get("quant_context")
    if quant_ctx and isinstance(quant_ctx, dict):
        prob = quant_ctx.get("probability", 0.5)
        regime = quant_ctx.get("regime", "UNKNOWN")
        parts.append(f"QUANT ENGINE: P={prob:.3f} in {regime} regime.")
        if 0.45 <= prob <= 0.55:
            parts.append(
                "Note: Quant probability is near-neutral. Rely primarily on Structural (Priority 2) and Aggression (Priority 1) data for your bias."
            )

    # Floating Volume Bubbles & Imbalances
    volume_bubbles = data.get("volume_bubbles", "")
    if volume_bubbles:
        parts.append(f"Volume bubbles: {volume_bubbles}")

    imbalance_desc = data.get("stacked_imbalances", "")
    if imbalance_desc:
        parts.append(imbalance_desc)

    return parts


def _build_core_amt_narrative(data: Dict[str, Any]) -> str:
    """Core logic to build Fabio Valentini's AMT narrative.

    NOW ALIGNED WITH FABIO'S THINKING PROCESS:
    1. Market State (balanced vs imbalanced → active model)
    2. Location (VAH/VAL/POC/LVN → entry zones)
    3. Aggression (CVD, delta, big orders → confirmation)

    Shared by both entry and overseer prompts to ensure context parity.
    """
    return render_entry_prompt(data)


def render_entry_prompt(fields: Dict[str, Any]) -> str:
    """Render the shared AMT entry narrative (SESSION/MARKET STATE/ORDER FLOW).

    Pure and side-effect-free. Used by both live inference (via
    build_entry_prompt) and the dataset renderer (scripts/dataset_render.py),
    which maps the training dataset's `key: value` rows onto the live
    market_data_ai vocabulary.

    Tolerates a partial key set: missing `session_name` defaults to the live
    NSE session, absent prior-* keys skip the PRIOR SESSION line, and a
    categorical `poc` ("above"/"below"/"middle") is emitted instead of the
    numeric location math. Never crashes on missing keys.

    The CALL/PUT option-mapping block and the JSON schema instruction are NOT
    part of this narrative — build_entry_prompt appends them for live inference
    only (the dataset system prompt already says "Output JSON only").
    """
    data = dict(fields)
    if isinstance(data.get("poc"), str):
        # Categorical dataset POC tag must not reach the numeric location math.
        data["poc_tag"] = data["poc"]
        data["poc"] = 0
    parts: list[str] = []
    parts.extend(_build_narrative_session_context(data))
    parts.extend(_build_narrative_market_state(data))
    parts.extend(_build_narrative_order_flow(data))
    parts.extend(_build_narrative_dataset_context(data))
    return " ".join(parts)


def _build_narrative_dataset_context(data: Dict[str, Any]) -> list[str]:
    """Emit dataset-remapped keys the live market_data_ai never sends.

    The training dataset encodes signal categorically (poc: above, phase:
    POWER_HOUR, absorption: at_VAH, ib_range: tight) plus flat numeric fields
    (entry/stop_pts/current/losses_today/...). Rendering them here lets a
    retrain on nifty_amt_data_livefmt see live-style prose. The live app never
    populates these keys, so build_entry_prompt output is unchanged.
    """
    parts: list[str] = []
    poc_tag = data.get("poc_tag", "")
    if poc_tag == "above":
        parts.append("POC: price below POC — sellers defending above.")
    elif poc_tag == "below":
        parts.append("POC: price above POC — buyers defending below.")
    elif poc_tag == "middle":
        parts.append("POC: price at POC — fair value, no edge.")
    phase = data.get("phase", "")
    if phase:
        parts.append(f"Phase: {phase}.")
    absorption = data.get("absorptionSide", "")
    if absorption:
        side = "VAH" if "VAH" in str(absorption).upper() else "VAL"
        parts.append(f"Absorption: absorbing at {side}.")
    ib_range = data.get("ib_range", "")
    if ib_range:
        parts.append(f"IB range: {ib_range}.")
    if data.get("atr_falling") == "yes":
        parts.append("ATR: falling — contraction, mean reversion bias.")
    note = data.get("note", "")
    if note:
        parts.append(f"NOTE: {note}.")
    for key in ("symbol", "time"):
        if data.get(key):
            parts.append(f"{key.upper()}: {data[key]}.")
    auction = []
    for key in (
        "entry",
        "stop_pts",
        "current",
        "losses_today",
        "profit_today",
        "spot",
        "futures",
        "basis",
        "level",
        "buffer",
        "preopen_poc",
        "account",
    ):
        value = data.get(key)
        if isinstance(value, (int, float)) and value != 0:
            auction.append(f"{key}={value:g}")
    if auction:
        parts.append("AUCTION: " + ", ".join(auction) + ".")
    return parts


# =====================================================================
# Prompt Builders
# =====================================================================


def build_entry_prompt(data: Dict[str, Any], allow_short: bool = False) -> str:
    """Build entry prompt using the core AMT narrative."""
    narrative = render_entry_prompt(data)

    # Add option-specific context for entry
    opt_parts = []
    iv = data.get("iv", 0)
    theta = data.get("theta", 0)
    if iv > 0:
        opt_parts.append(f"IV: {iv:.1%}. Theta: {theta:.1f}/day.")
    
    # Fix 1: Option type direction mapping instruction
    option_type = data.get("option_type", "UNKNOWN")
    if option_type in ("CALL", "PUT"):
        opt_parts.append(
            f"\n\nIMPORTANT: You are analyzing a {option_type} OPTION contract."
        )
        if option_type == "CALL":
            opt_parts.append(
                "- LONG = Buy Call (bullish bet on underlying)"
            )
            opt_parts.append(
                "- SHORT = Sell Call (bearish bet on underlying)"
            )
        else:  # PUT
            opt_parts.append(
                "- LONG = Buy Put (bearish bet on underlying)"
            )
            opt_parts.append(
                "- SHORT = Sell Put (bullish bet on underlying)"
            )
        opt_parts.append(
            "- Direction refers to the OPTION position direction, not the underlying"
        )
        opt_parts.append(
            "- Output direction as LONG/SHORT/FLAT for the option contract itself"
        )

    final_prompt = narrative
    if opt_parts:
        final_prompt += " " + " ".join(opt_parts)

    # ponytail: the CALL/PUT option-mapping block + JSON schema suffix are
    # build_entry_prompt-only — the training dataset has no option context and
    # its system prompt already says "Output JSON only", so render_entry_prompt
    # (shared with scripts/dataset_render.py) deliberately omits both.
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
    """Build 4-section overseer prompt per spec P3-3.

    Section 1: Position state (entry, current, unrealized, SL, TP, hold time)
    Section 2: Market context (AMT state, POC/VAH/VAL, aggression, CVD)
    Section 3: Risk constraints (tier, daily PnL, loss streak, daily loss %)
    Section 4: Instruction (action: HOLD/TIGHTEN_SL/PARTIAL_EXIT/FULL_EXIT/ADD)
    """

    def _safe_float(obj, attr, default=0.0):
        val = getattr(obj, attr, default)
        try:
            return float(val)
        except Exception:
            return default

    # Section 1: Position state
    entry = pos_state.get("entry_price", 0)
    current = pos_state.get("current_price", 0)
    unrealized_pct = pos_state.get("unrealized_pnl_pct", 0) * 100
    sl = pos_state.get("stop_loss", 0)
    tp = pos_state.get("take_profit", 0)
    hold_sec = pos_state.get("hold_time_seconds", 0)
    section_1 = (
        f"Side={pos_state.get('side', 'LONG')} "
        f"Entry={entry:.2f} Current={current:.2f} "
        f"Unrealized={unrealized_pct:+.2f}% "
        f"SL={sl:.2f} TP={tp:.2f} Hold={hold_sec:.0f}s"
    )

    # Section 2: Market context
    poc = _safe_float(amt_result, "poc")
    vah = getattr(amt_result, "value_area_high", getattr(amt_result, "vah", 0.0))
    val = getattr(amt_result, "value_area_low", getattr(amt_result, "val", 0.0))
    market_state = getattr(amt_result, "market_state", "Unknown")
    aggression = _safe_float(amt_result, "aggression")
    cvd_slope = getattr(amt_result, "cvd_slope", getattr(amt_result, "cvd", 0))
    delta_norm = _safe_float(tick, "delta")
    section_2 = (
        f"State={market_state} POC={poc:.2f} VAH={vah:.2f} VAL={val:.2f} "
        f"Aggression={aggression:.1f} CVD_slope={cvd_slope:.1f} Delta={delta_norm:.2f}"
    )

    # Section 3: Risk constraints
    tier = pos_state.get("risk_tier", "C")
    daily_pnl = pos_state.get("daily_pnl", 0)
    loss_streak = pos_state.get("consecutive_losses", 0)
    daily_loss_pct = pos_state.get("daily_loss_pct", 0)
    section_3 = (
        f"Tier={tier} DailyPnL={daily_pnl:.2f} "
        f"LossStreak={loss_streak} DailyLoss={daily_loss_pct:.2%}"
    )

    # Section 4: Instruction
    section_4 = "Action: HOLD | TIGHTEN_SL | PARTIAL_EXIT | FULL_EXIT | ADD. JSON only."

    # Build final prompt
    lines = [
        f"=== OVERSEER: {pos_state.get('symbol', '')} ===",
        f"[Position] {section_1}",
        f"[Market] {section_2}",
        f"[Risk] {section_3}",
        f"[Instruction] {section_4}",
    ]

    return "\n".join(lines) + "\n\n" + OVERSEER_INSTRUCTION


# =====================================================================
# Parsers
# =====================================================================


def parse_entry_response(text: str) -> Dict[str, Any]:
    """Parse model output into direction, trying JSON first then keyword fallback."""
    # Ensure text is not None and is a string
    text = str(text or "").strip()
    if not text:
        return {
            "direction": "FLAT",
            "rationale": "LLM returned empty response",
            "confidence": "High",
        }

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
    text = (raw or "").strip()
    if not text:
        return None

    # Try direct parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Extract JSON block — ensure text is not None and is a string
    text = str(raw or "").strip()
    if not text:
        return None

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        json_text = match.group(0)

        # Try direct parse of extracted block
        try:
            obj = json.loads(json_text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
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

    # FIX: Robustly extract rationale. Fallback to extracting text between symbols
    # if the rationale key is missing or empty to avoid JSON bleed.
    rationale = obj.get("rationale", "")
    if not rationale:
        # Try to strip common JSON markers and think blocks from the raw text
        cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)
        cleaned = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\{.*?\}", "", cleaned, flags=re.DOTALL).strip()
        rationale = cleaned or "No explicit rationale provided."

    return {
        "direction": direction,
        "rationale": rationale,
        "raw_output": raw_text,
        "confidence": confidence,
    }


def _normalize_overseer_json(obj: Dict[str, Any], pos_state: dict) -> OverseerAction:
    action = str(obj.get("action", "HOLD")).upper().replace(" ", "_").strip()
    if action not in {"HOLD", "TIGHTEN_SL", "PARTIAL_EXIT", "FULL_EXIT", "ADD"}:
        action = "HOLD"
    new_sl = obj.get("new_sl_price")
    if action == "TIGHTEN_SL" and (not isinstance(new_sl, (int, float)) or new_sl <= 0):
        new_sl = compute_tighten_sl(pos_state)

    reason = str(obj.get("reason", obj.get("rationale", ""))).strip()
    return OverseerAction(
        action=action,
        new_sl_price=float(new_sl)
        if isinstance(new_sl, (int, float)) and new_sl > 0
        else None,
        reason=reason or "Conviction unchanged.",
    )


def _try_structured_parse(text: str) -> Optional[Dict[str, Any]]:
    """Parse structured output formats including STATE:/TRADE: format."""
    # Check for STATE:/TRADE: format (Gemma 4 AMT model)
    state_match = re.search(r"STATE:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    trade_match = re.search(r"TRADE:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)

    if state_match and trade_match:
        state = state_match.group(1).strip().upper()
        trade = trade_match.group(1).strip().upper()

        # Map TRADE to direction
        if "LONG" in trade:
            direction = "LONG"
        elif "SHORT" in trade:
            direction = "SHORT"
        else:
            direction = "FLAT"

        # Map STATE to confidence
        if state in ["BREAKOUT", "TREND", "IMBALANCE"]:
            confidence = "High"
        elif state in ["REJECTION", "FAILED BREAKOUT", "EXHAUSTION"]:
            confidence = "Medium"
        else:
            confidence = "Low"

        return {
            "direction": direction,
            "rationale": f"AMT State: {state}, Trade: {trade}",
            "raw_output": text,
            "confidence": confidence,
        }

    # Legacy trigger: format
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


# =====================================================================
# Pre-Candle Advisory
# =====================================================================


def build_advisory_prompt(
    symbol: str,
    tick: "OHLC",
    amt_result: "AMTResult",
) -> str:
    """Build 5-section advisory prompt per spec P3-3.

    Section 1: Date + timeline context
    Section 2: Current 5-min bar data
    Section 3: AMT state (market state, POC/VAH/VAL, zone)
    Section 4: Aggression + CVD direction
    Section 5: Instruction (scenario narrative only)
    """

    bar_time = tick.time
    try:
        dt = datetime.fromisoformat(bar_time)
        section_1 = dt.strftime("%A, %B %d, %Y %H:%M IST")
    except Exception:
        section_1 = bar_time

    section_2 = (
        f"O={tick.open} H={tick.high} L={tick.low} C={tick.close} V={tick.volume}"
    )

    market_state = getattr(amt_result, "market_state", "UNKNOWN")
    poc = getattr(amt_result, "poc", 0)
    vah = getattr(amt_result, "value_area_high", 0)
    val = getattr(amt_result, "value_area_low", 0)
    zone = getattr(amt_result, "zone", "N/A")
    section_3 = f"State={market_state} POC={poc} VAH={vah} VAL={val} Zone={zone}"

    aggression = getattr(amt_result, "aggression", 0)
    cvd_slope = getattr(amt_result, "cvd_slope", 0)
    delta_norm = getattr(amt_result, "delta_normalized", 0)
    section_4 = (
        f"Aggression={aggression} CVD_slope={cvd_slope:.1f} Delta={delta_norm:.2f}"
    )

    lines = [
        f"=== PRE-CANDLE ADVISORY: {symbol} ===",
        f"[Date+Timeline] {section_1}",
        f"[Current Bar] {section_2}",
        f"[Market State] {section_3}",
        f"[Aggression] {section_4}",
    ]

    if getattr(amt_result, "lvns", None):
        lines.append(f"LVNs: {amt_result.lvns[:3]}")
    if getattr(amt_result, "hvns", None):
        lines.append(f"HVNs: {amt_result.hvns[:3]}")

    lines.append(
        "[Instruction] Scenario narrative for dashboard only. Not a trade signal."
    )
    return "\n".join(lines)


def parse_advisory_response(raw_response: str) -> Dict[str, str]:
    """Parse advisory LLM response into structured fields.

    Expects JSON: {"scenario": "...", "expected_setup": "...", "key_levels": "..."}
    Falls back to extracting from raw text.
    """
    try:
        # Try JSON parse
        match = re.search(r"\{[^{}]+\}", raw_response, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return {
                "scenario": parsed.get("scenario", ""),
                "expected_setup": parsed.get("expected_setup", ""),
                "key_levels": parsed.get("key_levels", ""),
            }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: return raw text as scenario
    return {
        "scenario": (raw_response or "").strip()[:200],
        "expected_setup": "",
        "key_levels": "",
    }
