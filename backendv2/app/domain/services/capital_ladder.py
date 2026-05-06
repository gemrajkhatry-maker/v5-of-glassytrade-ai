"""Capital ladder scaffolding for tiered add-on sizing."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RungState(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    HIT = "HIT"
    FAILED = "FAILED"


@dataclass
class CapitalRung:
    level: int = 0
    target_price: float = 0.0
    stop_price: float = 0.0
    size_pct: float = 0.0
    state: RungState = RungState.INACTIVE
    entry_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class LadderConfig:
    num_rungs: int = 3
    initial_size_pct: float = 0.4
    add_size_pct: float = 0.3
    trailing_stop_pct: float = 0.01


class CapitalLadder:
    def __init__(self, config: Optional[LadderConfig] = None):
        self.config = config or LadderConfig()
        self.rungs: list[CapitalRung] = []

    def build(
        self,
        entry_price: float,
        direction: str = "LONG",
        risk_pct: float = 0.01,
    ) -> list[CapitalRung]:
        self.rungs = []
        for i in range(self.config.num_rungs):
            size_pct = self.config.initial_size_pct if i == 0 else self.config.add_size_pct
            self.rungs.append(
                CapitalRung(
                    level=i,
                    target_price=float(entry_price),
                    stop_price=float(entry_price) * (1 - risk_pct if direction.upper() == "LONG" else 1 + risk_pct),
                    size_pct=size_pct,
                    state=RungState.INACTIVE,
                    entry_price=float(entry_price),
                )
            )
        return self.rungs

    def update(self, current_price: float, direction: str = "LONG") -> list[CapitalRung]:
        for rung in self.rungs:
            if rung.state != RungState.ACTIVE:
                continue
            if direction.upper() == "LONG" and current_price >= rung.target_price:
                rung.state = RungState.HIT
            if direction.upper() == "SHORT" and current_price <= rung.target_price:
                rung.state = RungState.HIT
        return self.rungs

    def get_active_rungs(self) -> list[CapitalRung]:
        return [r for r in self.rungs if r.state == RungState.ACTIVE]


RUNG_CONFIG = LadderConfig()

