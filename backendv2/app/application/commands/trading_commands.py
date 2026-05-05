"""Application commands for trading system."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UpdateTick:
    """Command to process a new market tick."""
    symbol: str
    timestamp: float
    price: float
    volume: float
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    order_book_bids: Optional[list] = None
    order_book_asks: Optional[list] = None


@dataclass(frozen=True)
class EvaluateEntry:
    """Command to evaluate entry opportunity."""
    symbol: str
    phase1_result: dict
    phase2_result: dict
    phase3_result: dict
    phase4_result: dict
    absorptions: list
    current_price: float
    vwap: float


@dataclass(frozen=True)
class CheckExit:
    """Command to check exit conditions for a position."""
    position_id: str
    current_price: float


@dataclass(frozen=True)
class OpenPosition:
    """Command to open a new position."""
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    size: float = 0.001


@dataclass(frozen=True)
class ClosePosition:
    """Command to close an existing position."""
    position_id: str
    exit_price: float
    reason: str = "SIGNAL"