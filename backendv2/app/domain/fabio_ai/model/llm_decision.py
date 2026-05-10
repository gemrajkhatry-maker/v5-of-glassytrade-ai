"""LLM decision value object.

Part of Fabio AI domain. Represents a parsed decision from the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LLMDecision"]


@dataclass(frozen=True)
class LLMDecision:
    """Structured output of the LLM entry helper."""

    direction: str
    confidence: str
    rationale: str
    input_prompt: str
    raw_output: str
    market_state: str
    tick_trace_id: str = ""
