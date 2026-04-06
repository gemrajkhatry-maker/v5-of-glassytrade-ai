"""Canonical LLM runtime contract for entry decisions.

This module defines the active paper-trading contract used by prompt
construction, inference, and parsing. Legacy structured text parsing remains
as a fallback for old checkpoints, but JSON is the canonical runtime format.
"""

from __future__ import annotations

from functools import lru_cache


ENTRY_CONTRACT_VERSION = "entry-json-v1"
CANONICAL_RUNTIME_MODEL_FAMILY = "qwen-mlx"

ENTRY_RESPONSE_KEYS: tuple[str, ...] = (
    "direction",
    "rationale",
    "confidence",
    "market_state",
)


@lru_cache(maxsize=2)
def entry_response_schema_instruction(*, allow_short: bool) -> str:
    """Return the canonical entry-response schema instruction.
    
    FABIO-ALIGNED: Forces clean JSON output for reliable parsing.
    """
    direction_choices = (
        '"LONG" | "SHORT" | "FLAT"' if allow_short else '"LONG" | "FLAT"'
    )
    return (
        '\n\nRespond with VALID JSON only (no markdown, no extra text):\n'
        '{\n'
        '  "direction": ' + direction_choices + ',\n'
        '  "confidence": "High" | "Medium" | "Low",\n'
        '  "rationale": "Brief justification referencing market state + location + aggression"\n'
        '}\n\n'
        'CRITICAL: Output ONLY the JSON object. No other text before or after.'
    )


ENTRY_JSON_RUNTIME_REMINDER = (
    "Return ONLY a valid JSON object with direction, confidence, and rationale keys. "
    "No markdown, no extra text, no prose outside the JSON."
)
