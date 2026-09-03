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
    def should_enter(self, ctx: "DecisionContext", *, allow_positioned: bool = False) -> "QuantDecision":
        """Evaluate entry conditions and return a decision.

        ``allow_positioned=True`` is the thesis-flip exit evaluation (an
        opposing-signal check against an OPEN position): it bypasses gate 2's
        open-position blocker and the risk-halt entry block — a halt gates
        ENTRIES, never the opposing-signal exit. Entries and positioned flips
        must flow through the SAME strategy seam so a swapped-in strategy
        governs both.

        Args:
            ctx: The decision context built by DecisionContextBuilder
            allow_positioned: Evaluate against an open position (thesis flip)

        Returns:
            A QuantDecision indicating whether to enter and with what signal
        """
        ...
