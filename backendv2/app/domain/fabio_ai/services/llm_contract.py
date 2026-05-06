"""LLM runtime contracts and prompt instructions."""

from __future__ import annotations

from functools import lru_cache

ENTRY_CONTRACT_VERSION = "entry-json-v1"
CANONICAL_RUNTIME_MODEL_FAMILY = "gemma-mlx"

ENTRY_RESPONSE_KEYS: tuple[str, ...] = (
    "direction",
    "rationale",
    "confidence",
    "market_state",
)


@lru_cache(maxsize=2)
def entry_response_schema_instruction(*, allow_short: bool) -> str:
    direction_choices = '"LONG" | "SHORT" | "FLAT"' if allow_short else '"LONG" | "FLAT"'
    return (
        "\n\nRespond with VALID JSON only (no markdown, no extra text):\n"
        "{\n"
        f'  "direction": {direction_choices},\n'
        '  "confidence": "High" | "Medium" | "Low",\n'
        '  "rationale": "Brief justification referencing market state + location + aggression",\n'
        '  "market_state": "BALANCED | IMBALANCED | PROBING"\n'
        "}\n\n"
        "CRITICAL: Output ONLY the JSON object. No prose outside JSON."
    )


ENTRY_JSON_RUNTIME_REMINDER = (
    "Return ONLY a valid JSON object with direction, confidence, and rationale keys. "
    "No markdown, no extra text, no prose outside the JSON."
)
