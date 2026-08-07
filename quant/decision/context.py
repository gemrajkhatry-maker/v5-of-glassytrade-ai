from dataclasses import dataclass
from typing import Optional

from quant.auction_state import AuctionState
from quant.bars import Bar


@dataclass(frozen=True)
class DecisionContext:
    state: Optional[AuctionState]  # the immutable snapshot
    bar: Optional[Bar]             # the bar that closed to produce state
    symbol: str = ""
    # session / risk facts
    session_open: bool = True
    warmup_complete: bool = True      # enough bars (> 15) for analysis
    position_open: bool = False
    cooldown_remaining_sec: int = 0
    risk_halted: bool = False
    consecutive_losses: int = 0
    # intended direction from a higher-level agent (may be None -> gates decide)
    agent_direction: Optional[str] = None   # "LONG" | "SHORT" | "FLAT" | None
    agent_probability: float = 0.0
    # capital for sizing
    equity: float = 1_000_000.0
    risk_per_trade_pct: float = 0.01
    tick_size: float = 0.05
