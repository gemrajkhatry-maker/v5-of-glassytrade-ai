"""Phase 1: Centralized EngineState.

Single source of truth for all engine state.
All transitions are pure functions returning NEW state (immutable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from quant.bars import Bar  # canonical single definition (was a local dataclass)


# ---------------------------------------------------------------------------
# Value Objects (frozen dataclasses)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionState:
    """Immutable position state."""
    id: str
    entry: float
    size: float
    sl: float
    tp: float
    side: str  # "LONG" | "SHORT"
    pyramid_level: int = 0
    is_pyramid: bool = False
    entry_time: str = ""


@dataclass(frozen=True)
class RiskState:
    """Immutable risk state."""
    daily_pnl: float = 0.0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""


# ---------------------------------------------------------------------------
# EngineState (single source of truth)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineState:
    """Centralized engine state. All transitions return NEW state."""
    
    symbol: str
    sequence: int = 0
    
    # Market state
    last_bar: Optional[Bar] = None
    
    # Position state (single source of truth)
    position: Optional[PositionState] = None
    pyramids: tuple[PositionState, ...] = ()
    
    # Risk state
    risk: RiskState = field(default_factory=RiskState)
    
    # Realized P&L accumulated through PositionClosed folds (base + pyramids).
    # Drives the fold-path portfolio equity so the WS snapshot reflects actual
    # trading results instead of the paper starting capital.
    realized_pnl: float = 0.0
    
    # Cooldown tracking
    last_close_bar: int = -1

    # Closed trades history (last N closed positions)
    closed_trades: tuple[dict, ...] = ()
    
    # Immutable transitions
    def with_bar(self, bar: Bar) -> EngineState:
        """Return new state with updated bar."""
        from dataclasses import replace
        return replace(self, last_bar=bar, sequence=self.sequence + 1)
    
    def with_position(self, pos: PositionState) -> EngineState:
        """Return new state with position set."""
        from dataclasses import replace
        return replace(self, position=pos, sequence=self.sequence + 1)
    
    def without_position(self) -> EngineState:
        """Return new state with position cleared."""
        from dataclasses import replace
        return replace(self, position=None, pyramids=(), sequence=self.sequence + 1)
    
    def with_risk(self, risk: RiskState) -> EngineState:
        """Return new state with updated risk."""
        from dataclasses import replace
        return replace(self, risk=risk, sequence=self.sequence + 1)
