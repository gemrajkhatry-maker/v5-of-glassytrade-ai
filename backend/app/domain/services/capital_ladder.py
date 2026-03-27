"""Capital Ladder — Fabio's progressive capital deployment model.

Defines 5 rungs of capital deployment based on time in market
and cumulative performance. Each rung increases risk and position count.

Rung 0: ₹5L, 1 position, 1-2 symbols (first 2 weeks)
Rung 1: ₹5L, 2 positions, 2-3 symbols (month 1-2)
Rung 2: ₹10L, 3 positions, 3-5 symbols (month 2-4)
Rung 3: ₹25L, 4 positions, 4-6 symbols (month 4-8)
Rung 4: ₹50L, 5 positions, 5-7 symbols (month 8+)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CapitalRung(int, Enum):
    RUNG_0 = 0
    RUNG_1 = 1
    RUNG_2 = 2
    RUNG_3 = 3
    RUNG_4 = 4


# Rung configuration per spec
RUNG_CONFIG: dict[CapitalRung, dict] = {
    CapitalRung.RUNG_0: {
        "capital": 500000,  # ₹5L
        "max_positions": 1,
        "max_symbols": 2,
        "min_days": 10,
        "min_trades": 20,
    },
    CapitalRung.RUNG_1: {
        "capital": 500000,  # ₹5L
        "max_positions": 2,
        "max_symbols": 3,
        "min_days": 30,
        "min_trades": 50,
    },
    CapitalRung.RUNG_2: {
        "capital": 1000000,  # ₹10L
        "max_positions": 3,
        "max_symbols": 5,
        "min_days": 60,
        "min_trades": 150,
    },
    CapitalRung.RUNG_3: {
        "capital": 2500000,  # ₹25L
        "max_positions": 4,
        "max_symbols": 6,
        "min_days": 120,
        "min_trades": 300,
    },
    CapitalRung.RUNG_4: {
        "capital": 5000000,  # ₹50L
        "max_positions": 5,
        "max_symbols": 7,
        "min_days": 240,
        "min_trades": 500,
    },
}


@dataclass(frozen=True)
class RungState:
    """Current capital ladder state."""

    current_rung: CapitalRung
    capital: int
    max_positions: int
    max_symbols: int
    days_in_rung: int
    total_trades: int
    can_advance: bool
    next_rung_requirements: str


class CapitalLadder:
    """Capital ladder — progressive capital deployment.

    Tracks days and trades to determine when to advance to next rung.
    Every capital increase requires a week of validation at the new level.
    """

    def __init__(self, starting_rung: CapitalRung = CapitalRung.RUNG_0) -> None:
        self._current_rung = starting_rung
        self._days_in_rung = 0
        self._total_trades = 0
        self._last_advance_date: str = ""

    @property
    def current_rung(self) -> CapitalRung:
        return self._current_rung

    @property
    def capital(self) -> int:
        return RUNG_CONFIG[self._current_rung]["capital"]

    @property
    def max_positions(self) -> int:
        return RUNG_CONFIG[self._current_rung]["max_positions"]

    @property
    def max_symbols(self) -> int:
        return RUNG_CONFIG[self._current_rung]["max_symbols"]

    def record_trade(self) -> None:
        """Record a trade for advancement tracking."""
        self._total_trades += 1

    def record_day(self) -> None:
        """Record a trading day."""
        self._days_in_rung += 1

    def can_advance(self) -> bool:
        """Check if current rung requirements are met."""
        cfg = RUNG_CONFIG[self._current_rung]
        return (
            self._days_in_rung >= cfg["min_days"]
            and self._total_trades >= cfg["min_trades"]
            and self._current_rung.value < 4
        )

    def advance(self) -> bool:
        """Advance to next rung if requirements met. Returns True if advanced."""
        if not self.can_advance():
            return False

        next_rung = CapitalRung(self._current_rung.value + 1)
        prev_rung = self._current_rung
        self._current_rung = next_rung
        self._days_in_rung = 0  # reset for new rung validation

        logger.info(
            "Capital Ladder: %s → %s (capital=₹%s, positions=%d, symbols=%d)",
            prev_rung.name,
            next_rung.name,
            f"{RUNG_CONFIG[next_rung]['capital']:,}",
            RUNG_CONFIG[next_rung]["max_positions"],
            RUNG_CONFIG[next_rung]["max_symbols"],
        )
        return True

    def get_state(self) -> RungState:
        """Get current ladder state."""
        cfg = RUNG_CONFIG[self._current_rung]
        next_cfg = RUNG_CONFIG.get(CapitalRung(self._current_rung.value + 1))

        if next_cfg:
            req = f"{next_cfg['min_days']}d + {next_cfg['min_trades']} trades"
        else:
            req = "MAX RUNG"

        return RungState(
            current_rung=self._current_rung,
            capital=cfg["capital"],
            max_positions=cfg["max_positions"],
            max_symbols=cfg["max_symbols"],
            days_in_rung=self._days_in_rung,
            total_trades=self._total_trades,
            can_advance=self.can_advance(),
            next_rung_requirements=req,
        )

    def to_dict(self) -> dict:
        return {
            "rung": self._current_rung.value,
            "days": self._days_in_rung,
            "trades": self._total_trades,
        }

    def load_from_dict(self, data: dict) -> None:
        self._current_rung = CapitalRung(data.get("rung", 0))
        self._days_in_rung = data.get("days", 0)
        self._total_trades = data.get("trades", 0)
