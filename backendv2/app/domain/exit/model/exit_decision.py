"""Domain exit decision.

Represents a decision to exit a position, used in pipeline events.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ExitDecision:
    """Decision to exit a position."""

    exit_type: str  # "FULL", "PARTIAL", "TRAIL"
    size_pct: float  # 0.0 to 1.0
    price: float
    reason: str
    new_stop: Optional[float] = None
