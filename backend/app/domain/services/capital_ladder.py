"""Capital Ladder — Stub.

Planned feature: Tiered position management using a capital ladder
where positions move between rungs (initial, partial, full) based on
price action and realized PnL.

Status: Stub — types defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RungState(str, Enum):
    """State of a capital ladder rung."""
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    HIT = "HIT"
    FAILED = "FAILED"


@dataclass
class CapitalRung:
    """Single rung in the capital ladder."""
    level: int = 0
    target_price: float = 0.0
    stop_price: float = 0.0
    size_pct: float = 0.0
    state: RungState = RungState.INACTIVE
    entry_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class LadderConfig:
    """Configuration for the capital ladder."""
    num_rungs: int = 3
    initial_size_pct: float = 0.4
    add_size_pct: float = 0.3
    trailing_stop_pct: float = 0.01


class CapitalLadder:
    """Capital ladder for tiered position management.

    Stub implementation — returns a single default rung.
    """

    def __init__(self, config: Optional[LadderConfig] = None):
        self.config = config or LadderConfig()
        self.rungs: list[CapitalRung] = []

    def build(
        self,
        entry_price: float,
        direction: str = "LONG",
        risk_pct: float = 0.01,
    ) -> list[CapitalRung]:
        """Build a ladder of rungs from entry price."""
        self.rungs = []
        for i in range(self.config.num_rungs):
            if i == 0:
                size = self.config.initial_size_pct
            else:
                size = self.config.add_size_pct

            self.rungs.append(CapitalRung(
                level=i,
                target_price=entry_price,
                stop_price=entry_price,
                size_pct=size,
                state=RungState.INACTIVE,
                entry_price=entry_price,
            ))
        return self.rungs

    def update(
        self,
        current_price: float,
        direction: str = "LONG",
    ) -> list[CapitalRung]:
        """Update rung states based on current price."""
        return self.rungs

    def get_active_rungs(self) -> list[CapitalRung]:
        """Return active rungs."""
        return [r for r in self.rungs if r.state == RungState.ACTIVE]


# Module-level constant for default config
RUNG_CONFIG = LadderConfig()
