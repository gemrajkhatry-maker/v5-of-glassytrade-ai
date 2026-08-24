"""Exit signal — immutable record of an exit decision.

This module is isolated to break the dependency cycle between
exit_engine.py and exit_rules.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExitSignal:
    """Returned by exit rule checks when an exit is triggered."""

    position_id: str
    reason: str
    exit_price: float
