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
    """Return the canonical entry-response schema instruction."""
    direction_choices = (
        '"LONG" | "SHORT" | "FLAT"' if allow_short else '"LONG" | "FLAT"'
    )
    return (
        "\n\nRespond in this structured format for the UI:\n"
        "Market State: <Balance or Imbalance>\n"
        "Logic: <professional justification referencing market state + location + aggression>\n"
        f"Trigger: <{direction_choices}> (High | Medium | Low confidence)"
    )


ENTRY_JSON_RUNTIME_REMINDER = (
    "Return exactly three lines: Market State, Logic, and Trigger. "
    "Do not add markdown, JSON braces, or prose outside this structure."
)
