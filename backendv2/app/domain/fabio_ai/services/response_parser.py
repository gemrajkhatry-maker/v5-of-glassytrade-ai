"""Response parsing for LLM outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel


class OverseerAction(BaseModel):
    """Parsed overseer action."""

    action: str = "HOLD"
    urgency: str = "NORMAL"
    confidence: float = 0.0
    rationale: str = ""


def parse_entry_response(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    json_payload = _try_parse_json(text)
    if json_payload is not None:
        return _normalize_entry_json(json_payload, text)

    structured = _try_structured_parse(text)
    if structured is not None:
        return _normalize_entry_json(structured, text)

    return _keyword_fallback_parse(text)


def parse_overseer_response(text: str, pos_state: dict) -> OverseerAction:
    try:
        data = json.loads(text)
        return OverseerAction(
            action=data.get("action", "HOLD"),
            urgency=data.get("urgency", "NORMAL"),
            confidence=float(data.get("confidence", 0.0)),
            rationale=data.get("rationale", ""),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    json_payload = _try_parse_json(text)
    if isinstance(json_payload, dict):
        return _normalize_overseer_json(json_payload, pos_state)

    return _keyword_fallback_parse_overseer(text, pos_state)


def _try_parse_json(raw: str) -> Optional[dict[str, Any]]:
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group())
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return None
    return None


def _normalize_entry_json(obj: dict[str, Any], raw_text: str) -> dict[str, Any]:
    direction = str(obj.get("direction", "FLAT")).upper()
    if direction not in {"LONG", "SHORT", "FLAT"}:
        direction = "FLAT"
    confidence = str(obj.get("confidence", obj.get("probability", "Medium")))
    conf_map = {
        "1": "High",
        "2": "Low",
        "3": "Low",
        "4": "Medium",
        "5": "Medium",
        "0.0": "Low",
    }
    if isinstance(confidence, str):
        conf_key = confidence.strip().lower()
        if conf_key in conf_map:
            conf = conf_map[conf_key]
        elif conf_key in {"h", "high", "strong"}:
            conf = "High"
        elif conf_key in {"l", "low", "weak"}:
            conf = "Low"
        elif conf_key in {"m", "medium", "avg"}:
            conf = "Medium"
        else:
            conf = "Medium"
    else:
        conf = "Medium"
    return {
        "direction": direction,
        "confidence": conf,
        "rationale": _str_preview(obj.get("rationale", raw_text)),
    }


def _try_structured_parse(text: str) -> Optional[dict[str, Any]]:
    lines = text.strip().split("\n")
    result: dict[str, Any] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"direction", "signal"}:
            result["direction"] = value.upper()
        elif key in {"confidence", "probability"}:
            try:
                num = float(value.replace("%", ""))
                if num > 1:
                    num = num / 100.0
                result["confidence"] = round(max(0.0, min(1.0, num)), 4)
            except ValueError:
                pass
        elif key == "rationale":
            result["rationale"] = value
    if not result:
        return None
    if "confidence" in result and "rationale" not in result:
        result["rationale"] = "Parsed from structured fields."
    return result


def _keyword_fallback_parse(text: str) -> dict[str, Any]:
    text_upper = text.upper()
    if "LONG" in text_upper or "BUY" in text_upper:
        direction = "LONG"
    elif "SHORT" in text_upper or "SELL" in text_upper:
        direction = "SHORT"
    else:
        direction = "FLAT"

    conf_match = re.search(r"(\d+(?:\.\d+)?)%?", text)
    confidence = float(conf_match.group(1)) / 100 if conf_match else 0.5
    confidence = min(1.0, max(0.0, confidence))
    return {
        "direction": direction,
        "confidence": f"{confidence:.0%}",
        "rationale": _str_preview(text),
    }


def _normalize_overseer_json(obj: dict[str, Any], pos_state: dict) -> OverseerAction:
    return OverseerAction(
        action=obj.get("action", "HOLD"),
        urgency=obj.get("urgency", "NORMAL"),
        confidence=float(obj.get("confidence", 0.0)),
        rationale=obj.get("rationale", ""),
    )


def _keyword_fallback_parse_overseer(text: str, pos_state: dict) -> OverseerAction:
    text_upper = text.upper()
    if "EXIT" in text_upper:
        action = "EXIT"
    elif "ADD" in text_upper or "SCALE" in text_upper:
        action = "ADD"
    elif "MOVE" in text_upper or "ADJUST" in text_upper:
        action = "MOVE_SL"
    else:
        action = "HOLD"

    urgency = "HIGH" if "URGENT" in text_upper else "NORMAL"
    confidence = 0.0
    confidence_match = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if confidence_match:
        confidence = min(1.0, max(0.0, float(confidence_match.group(1)) / 100))
    return OverseerAction(
        action=action,
        urgency=urgency,
        confidence=confidence,
        rationale=_str_preview(text),
    )


def _str_preview(value: object) -> str:
    text = str(value)
    return text[:140] if len(text) > 140 else text

