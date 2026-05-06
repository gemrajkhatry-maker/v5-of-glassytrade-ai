"""Prompt templates and response parsers for LLM-assisted decisioning."""
from __future__ import annotations

from json import dumps
from typing import Any

from app.domain.amt.service.narrative_builder import _build_core_amt_narrative
from app.domain.fabio_ai.services.llm_contract import ENTRY_JSON_RUNTIME_REMINDER
from app.domain.fabio_ai.services.response_parser import (
    OverseerAction,
    parse_entry_response,
    parse_overseer_response,
)


def _as_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_narrative_session_context(data: dict[str, Any]) -> str:
    parts = []
    if data.get("session_name"):
        parts.append(f"Session: {data['session_name']}.")
    if data.get("favor_strategy") and data["favor_strategy"] != "NEUTRAL":
        parts.append(f"Active bias: {data['favor_strategy']}.")
    if data.get("prior_poc"):
        parts.append(
            f"Prior POC/VAH/VAL: {data.get('prior_poc', 0):.0f}/{data.get('prior_vah', 0):.0f}/{data.get('prior_val', 0):.0f}."
        )
    if data.get("gap_type"):
        parts.append(f"Gap: {data['gap_type']}.")
    if data.get("opening_bias"):
        parts.append(f"Opening bias: {data['opening_bias']}.")
    return "\n".join(parts) if parts else "No session context supplied."


def _build_narrative_market_state(data: dict[str, Any]) -> str:
    price = _as_float(data.get("ltp"))
    poc = _as_float(data.get("poc"))
    vah = _as_float(data.get("vah"))
    val = _as_float(data.get("val"))
    market_state = _as_str(data.get("market_state", "BALANCED")).upper()
    if market_state in {"IMBALANCED", "TRADING"}:
        return (
            f"Market state: IMBALANCED. Price {price:.2f} outside prior VA "
            f"({val:.2f}-{vah:.2f})."
        )
    return (
        f"Market state: BALANCED. Price {price:.2f} near/value area "
        f"({val:.2f}-{vah:.2f}) around POC {poc:.2f}."
    )


def _build_narrative_order_flow(data: dict[str, Any]) -> str:
    parts: list[str] = []
    delta = _as_float(data.get("delta"))
    aggression = _as_float(data.get("aggression"))
    cvd_slope = _as_float(data.get("cvd_slope"))
    if abs(delta) > 0:
        polarity = "BUY" if delta > 0 else "SELL"
        parts.append(f"Delta: {polarity} momentum ({delta:.2f}).")
    if abs(aggression) > 0:
        parts.append(f"Aggression score: {aggression:.2f}.")
    if abs(cvd_slope) > 0:
        parts.append(f"CVD slope: {cvd_slope:.2f}.")
    return "\n".join(parts) if parts else "No order-flow confirmation."


def build_entry_prompt(data: dict[str, Any], allow_short: bool = False) -> str:
    """Build the prompt for entry direction calls.

    The prompt keeps a strict contract with parse_entry_response and instructs JSON-only
    output with explicit fallback fields.
    """
    core = "\n".join(
        [
            _build_narrative_session_context(data),
            _build_narrative_market_state(data),
            _build_narrative_order_flow(data),
            _build_core_amt_narrative(data),
        ]
    )
    direction_constraint = "LONG or FLAT only" if not allow_short else "LONG or SHORT or FLAT"
    return (
        "You are reading auction market structure using Fabio AMT methodology.\n"
        "Return only a JSON object with keys: direction, confidence, rationale.\n"
        f"Direction options: {direction_constraint}.\n"
        "Confidence options: High / Medium / Low.\n"
        f"{ENTRY_JSON_RUNTIME_REMINDER}\n"
        f"Rationale MUST reference market structure and order-flow.\n"
        f"Snapshot:\n{core}\n"
        f"Raw context:\n{dumps(data, default=str)}"
    )


def build_overseer_prompt(data: dict[str, Any], position_state: dict[str, Any]) -> str:
    """Build prompt for post-entry overseer decision."""
    payload = {"position": position_state, "market": data}
    return (
        "You are a protective trading overseer.\n"
        "Return JSON only with keys: action, urgency, confidence, rationale.\n"
        "action options: HOLD, EXIT, ADD, MOVE_SL, WAIT.\n"
        "urgency options: LOW, NORMAL, HIGH.\n"
        f"Input:\n{dumps(payload, default=str)}"
    )


def build_advisory_prompt(data: dict[str, Any]) -> str:
    symbol = _as_str(data.get("symbol"), "UNKNOWN")
    message = _as_str(data.get("message"), "No message")
    return (
        "You are a concise trading copy assistant. Return JSON with key `text` only.\n"
        f"symbol={symbol}\n"
        f"message={message}"
    )


def parse_entry_response(text: str) -> dict[str, Any]:
    return parse_entry_response(text)


def parse_overseer_response(text: str, pos_state: dict[str, Any]) -> OverseerAction:
    return parse_overseer_response(text, pos_state)


def parse_advisory_response(raw_response: str) -> dict[str, str]:
    return {
        "text": parse_overseer_response(raw_response, {}).rationale
        if isinstance(raw_response, str) and raw_response.strip()
        else ""
    }


def compute_tighten_sl(pos_state: dict[str, Any]) -> float:
    """Small helper to widen SL by a small fraction during deterioration."""
    try:
        direction = str(pos_state.get("direction", "")).upper()
        stop_loss = float(pos_state.get("stop_loss", 0.0))
        entry = float(pos_state.get("entry_price", 0.0))
    except (TypeError, ValueError):
        return 0.0
    if stop_loss <= 0 or entry <= 0:
        return 0.0
    if direction == "LONG":
        return max(stop_loss, entry - abs(entry - stop_loss) * 0.67)
    if direction == "SHORT":
        return min(stop_loss, entry + abs(entry - stop_loss) * 0.67)
    return stop_loss

