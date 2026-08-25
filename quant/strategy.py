"""Trading strategy protocol — the seam for pluggable strategies."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from quant.auction_state import AuctionState
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import QuantDecision


class TradingStrategy(Protocol):
    """Protocol for pluggable trading strategies.
    
    Implementations must provide two methods:
    - on_bar: Update internal state on each bar close
    - should_enter: Evaluate entry conditions
    The strategy receives the auction state, bar, and AMT DTO as inputs.
    PositionManager owns position exits.
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
