"""Session runtime contracts for deterministic orchestration boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TickTraceContract:
    """Canonical trace metadata for a TickReceived ingress event."""

    trace_id: str
    sequence: int
    symbol: str
    tick_time: str


@dataclass(frozen=True)
class EntryDecisionContract:
    """Canonical result of session entry decision resolution."""

    exec_decision: Any | None
    exec_amt: Any | None
    exec_tick: Any | None
    exec_dir: str
    exec_prob: float
    run_entry: bool


@dataclass(frozen=True)
class LLMTriggerContract:
    """LLM trigger decisions derived from the current tick contract."""

    trigger_llm: bool
    monitoring_trigger: bool
    event_trigger: bool = False
