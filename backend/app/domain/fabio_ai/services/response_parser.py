"""Response parsing for LLM outputs.

Extracted from prompt_builder.py for separation of concerns.
"""

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
    """Parse entry LLM response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try structured parse
    result = _try_structured_parse(text)
    if result:
        return result
    
    # Fallback to keyword extraction
    return _keyword_fallback_parse(text)


def parse_overseer_response(text: str, pos_state: dict) -> OverseerAction:
    """Parse overseer LLM response."""
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
    
    return _keyword_fallback_parse_overseer(text, pos_state)


def _try_parse_json(raw: str) -> Optional[dict[str, Any]]:
    """Try to extract JSON from text."""
    # Try to find JSON object in text
    match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _normalize_entry_json(obj: dict[str, Any], raw_text: str) -> dict[str, Any]:
    """Normalize entry JSON to standard format."""
    return {
        "direction": obj.get("direction", "FLAT"),
        "confidence": float(obj.get("confidence", 0.5)),
        "rationale": obj.get("rationale", raw_text[:100]),
    }


def _try_structured_parse(text: str) -> Optional[dict[str, Any]]:
    """Try structured text parsing."""
    lines = text.strip().split("\n")
    result = {}
    
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in ("direction", "signal"):
                result[key] = value.upper()
            elif key in ("confidence", "probability"):
                try:
                    result[key] = float(value)
                except ValueError:
                    pass
            elif key == "rationale":
                result[key] = value
    
    return result if result else None


def _keyword_fallback_parse(text: str) -> dict[str, Any]:
    """Extract meaning from keywords."""
    text_upper = text.upper()
    
    if "LONG" in text_upper or "BUY" in text_upper:
        direction = "LONG"
    elif "SHORT" in text_upper or "SELL" in text_upper:
        direction = "SHORT"
    else:
        direction = "FLAT"
    
    # Extract confidence from patterns like "85%" or "0.85"
    conf_match = re.search(r'(\d+)%?', text)
    confidence = float(conf_match.group(1)) / 100 if conf_match else 0.5
    
    return {
        "direction": direction,
        "confidence": min(confidence, 1.0),
        "rationale": text[:100],
    }


def _normalize_overseer_json(obj: dict[str, Any], pos_state: dict) -> OverseerAction:
    """Normalize overseer JSON."""
    return OverseerAction(
        action=obj.get("action", "HOLD"),
        urgency=obj.get("urgency", "NORMAL"),
        confidence=float(obj.get("confidence", 0.0)),
        rationale=obj.get("rationale", ""),
    )


def _keyword_fallback_parse_overseer(text: str, pos_state: dict) -> OverseerAction:
    """Extract overseer action from keywords."""
    text_upper = text.upper()
    
    if "EXIT" in text_upper:
        action = "EXIT"
    elif "ADD" in text_upper or "SCALE" in text_upper:
        action = "ADD"
    elif "MOVE" in text_upper or "ADJUST" in text_upper:
        action = "MOVE_SL"
    else:
        action = "HOLD"
    
    if "URGENT" in text_upper or "NOW" in text_upper:
        urgency = "URGENT"
    else:
        urgency = "NORMAL"
    
    return OverseerAction(
        action=action,
        urgency=urgency,
        confidence=0.5,
        rationale=text[:100],
    )


def compute_tighten_sl(pos_state: dict) -> float:
    """Compute stop loss tighten factor."""
    # If in profit, tighten SL
    mfe = pos_state.get("mfe", 0)
    entry = pos_state.get("entry_price", 0)
    sl = pos_state.get("stop_loss", 0)
    
    if entry > 0 and sl > 0:
        profit = entry - sl
        if profit > 0:
            return max(0.5, 1.0 - profit / entry)
    return 1.0