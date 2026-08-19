"""Trading strategy protocol — the seam for pluggable strategies.

A TradingStrategy encapsulates the decision logic for when to enter and exit
positions. The QuantEngine delegates to the strategy for these decisions,
making it possible to swap strategies (AMT scalping, momentum, mean-reversion,
etc.) without modifying the engine core.

The protocol defines three hooks:
- on_bar: Called on each bar close to update strategy state
- should_enter: Evaluate entry conditions and return a decision
- should_exit: Evaluate exit conditions for an open position

The default implementation is AmtScalpingStrategy in quant/strategies/amt_scalping.py.
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from quant.auction_state import AuctionState
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import QuantDecision
    from quant.execution.exits import ExitDecision


class TradingStrategy(Protocol):
    """Protocol for pluggable trading strategies.
    
    Implementations must provide three methods:
    - on_bar: Update internal state on each bar close
    - should_enter: Evaluate entry conditions
    - should_exit: Evaluate exit conditions
    
    The strategy receives the auction state, bar, and AMT DTO as inputs
    and returns decisions. The engine handles position management, event
    emission, and risk tracking.
    """

    def on_bar(self, bar: "Bar", auction: "AuctionState", amt_dto: dict) -> None:
        """Called on each bar close to update strategy state.
        
        Args:
            bar: The closed bar
            auction: Current auction state from the coordinator
            amt_dto: AMT analysis DTO
        """
        ...

    def should_enter(self, ctx: "DecisionContext") -> "QuantDecision":
        """Evaluate entry conditions and return a decision.
        
        Args:
            ctx: The decision context built by DecisionContextBuilder
            
        Returns:
            A QuantDecision indicating whether to enter and with what signal
        """
        ...

    def should_exit(
        self,
        position,
        state: "AuctionState",
        bar: "Bar",
        held_bars: int,
    ) -> "ExitDecision":
        """Evaluate exit conditions for an open position.
        
        Args:
            position: The open position
            state: Current auction state
            bar: The current bar
            held_bars: Number of bars the position has been held
            
        Returns:
            An ExitDecision indicating whether to exit
        """
        ...
