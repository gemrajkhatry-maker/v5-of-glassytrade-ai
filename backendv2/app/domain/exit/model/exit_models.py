"""Exit domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    SCRATCH = "SCRATCH"
    BREAK_EVEN = "BREAK_EVEN"
    OVERSEER_EXIT = "OVERSEER_EXIT"
    OVERSEER_PARTIAL = "OVERSEER_PARTIAL"
    SPREAD_BLOWOUT = "SPREAD_BLOWOUT"
    ADVERSE_EXIT = "ADVERSE_EXIT"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class ExitSignal:
    """Signal to exit (part of) a position."""
    exit_type: str  # "FULL" | "PARTIAL" | "TRAIL"
    size_pct: float  # 0.0-1.0 (fraction of position to exit)
    price: float
    reason: str
    new_stop: float | None = None  # New SL after partial exit





@dataclass
class PartitionState:
    """Tracks which partitions have been taken."""
    p1_taken: bool = False
    p2_taken: bool = False
    p3_taken: bool = False
    breakeven_set: bool = False
    counter_aggression_count: int = 0
    trail_sl: float = 0.0


@dataclass(frozen=True)
class PyramidSignal:
    """Signal to add to a winning position."""
    size_multiplier: float  # 1.0 = 100% of base, 0.5 = 50% of base
    level: float  # Price level for the add
    unified_sl: float  # New stop loss for all entries


class StopReason(str, Enum):
    LVN = "LVN"
    VA_BOUNDARY = "VA_BOUNDARY"
    IB_EXTREME = "IB_EXTREME"
    PROBE_EXTREME = "PROBE_EXTREME"
    HVN = "HVN"
    ATR_CAP = "ATR_CAP"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True)
class StructuralStop:
    """Computed structural stop loss."""
    price: float
    reason: str
    distance_from_entry: float
    distance_pct: float
    atr_multiple: float
    thesis: str
