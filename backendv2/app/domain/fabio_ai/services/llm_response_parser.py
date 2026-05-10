"""LLM response parsing utilities.

Extracted from LLMEntryHandler. Provides parsing, normalization, and
sanitization logic used to convert raw LLM output into structured decisions.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _normalize_direction(value: str | None) -> str:
    """Normalize direction token to one of LONG, SHORT, FLAT (uppercase)."""
    if not value:
        return "FLAT"
    v = str(value).strip().upper()
    if v in ("LONG", "BUY", "BULL", "CALL"):
        return "LONG"
    if v in ("SHORT", "SELL", "BEAR", "PUT"):
        return "SHORT"
    if v in ("FLAT", "HOLD", "NEUTRAL", "CASH"):
        return "FLAT"
    return "FLAT"


def _normalize_confidence(value: str | None) -> str:
    """Normalize confidence to HIGH/MEDIUM/LOW (uppercase)."""
    if value is None:
        return "MEDIUM"
    v = str(value).strip()
    if not v:
        return "MEDIUM"
    lower = v.lower()
    if lower in {"high", "h", "strong"}:
        return "HIGH"
    if lower in {"medium", "med", "m", "moderate"}:
        return "MEDIUM"
    if lower in {"low", "l", "weak"}:
        return "LOW"
    # Numeric 0-1 or 0-100?
    try:
        num = float(v)
        if 0 <= num <= 1:
            return "HIGH" if num >= 0.8 else "MEDIUM" if num >= 0.5 else "LOW"
        if 0 <= num <= 100:
            return "HIGH" if num >= 80 else "MEDIUM" if num >= 50 else "LOW"
    except Exception:
        pass
    return "MEDIUM"


class LLMResponseParser:
    """Parser for LLM text responses."""

    @staticmethod
    def parse(text: str) -> dict | None:
        """Extract a JSON object from text and return a dict with keys.

        Returns None if no valid JSON is found.
        """
        if not text or not text.strip():
            return None

        # Try to locate a JSON object via braces
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            json_blob = text[start:end]
            data = json.loads(json_blob)
        except (ValueError, json.JSONDecodeError):
            return None

        if not isinstance(data, dict):
            return None

        # Determine direction
        direction = None
        for key in ("direction", "signal", "action"):
            if key in data:
                direction = _normalize_direction(str(data[key]))
                break
        if direction is None:
            return None

        # Determine confidence
        confidence = None
        for key in ("confidence", "score", "probability", "prob"):
            if key in data:
                confidence = _normalize_confidence(str(data[key]))
                break
        if confidence is None:
            confidence = "MEDIUM"

        # Rationale
        rationale = (
            data.get("rationale")
            or data.get("analysis")
            or data.get("reason")
            or ""
        )
        rationale = str(rationale).strip()
        logger.debug("[PARSER] parsed JSON dir=%s conf=%s", direction, confidence)
        return {"direction": direction, "confidence": confidence, "rationale": rationale}

    @staticmethod
    def parse_line_based(text: str) -> dict | None:
        """Parse key=value lines (e.g., 'direction=LONG') into a dict.

        Supports keys: direction, confidence, rationale (case-insensitive keys).
        Returns None if direction is missing.
        """
        payload: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if not value:
                continue
            payload[key] = value

        if "direction" not in payload:
            return None

        direction = _normalize_direction(payload["direction"])
        confidence = _normalize_confidence(payload.get("confidence")) or "MEDIUM"
        rationale = payload.get("rationale", "")
        return {"direction": direction, "confidence": confidence, "rationale": rationale}

    @staticmethod
    def sanitize(raw_rationale: str, direction: str) -> str:
        """Strip JSON artifacts, remove LLM notes, and normalize ending."""
        if not raw_rationale:
            return f"{direction} signal — no rationale provided."

        text = str(raw_rationale).strip()

        # Remove parenthetical notes like "(Note: ...)" on their own line or inline
        text = re.sub(r"\(Note:.*?\)", "", text, flags=re.IGNORECASE)

        # If there is a JSON object embedded, extract rationale field if possible
        if text.startswith("{") and "}" in text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "rationale" in parsed:
                    text = str(parsed["rationale"]).strip()
            except (json.JSONDecodeError, ValueError):
                pass

        # Remove any remaining braces artifacts
        if "{" in text and "}" in text:
            json_match = re.search(r"\{[^{}]*\"rationale\"[^{}]*\}", text, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, dict) and "rationale" in parsed:
                        text = str(parsed["rationale"]).strip()
                except (json.JSONDecodeError, ValueError):
                    pass
            text = re.sub(r"\{[^}]*\}", "", text)

        # Normalize whitespace
        text = text.replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return f"{direction} signal — no rationale provided."

        # If the text contains the opposite direction word at the start, truncate
        # This is a simple heuristic to handle mismatches.
        up_dir = direction.upper()
        # Check if text starts with an opposite direction
        # If direction is LONG and text starts with SHORT, or vice versa, cut it off.
        if up_dir == "LONG" and text.upper().startswith("SHORT"):
            text = ""
        elif up_dir == "SHORT" and text.upper().startswith("LONG"):
            text = ""
        elif up_dir == "FLAT":
            # For FLAT, any directional lead might be trimmed
            if text.upper().startswith(("LONG", "SHORT")):
                text = ""

        if not text:
            return f"{direction} signal — no rationale provided."

        # Ensure sentence ends with a period
        if not text.endswith((".", "!", "?")):
            text = text.rstrip() + "."

        return text
