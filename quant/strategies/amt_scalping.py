"""AMT Scalping Strategy — the Fabio Valentini playbook.

This is the default strategy that encodes the Auction Market Theory scalping
logic: trade the Triple-A edge (absorption -> accumulation -> aggression),
respect session gates, and manage exits via the ExitEngine.

The strategy delegates to:
- DecisionService for entry evaluation (gates 1-4 + signal builder)
- ExitEngine for exit evaluation (trail stop, time stop, session close)

This strategy can be swapped for alternatives (momentum, mean-reversion, etc.)
by implementing the TradingStrategy protocol.
"""

from __future__ import annotations

from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService, QuantDecision
from quant.execution.exits import ExitEngine


class AmtScalpingStrategy:
    """AMT scalping strategy — the Fabio Valentini playbook.
    
    Entry: Triple-A edge (absorption -> accumulation -> aggression) with
    R:R >= 1.5, passing all 4 gates (session, cooldown, edge, risk-reward).
    
    Exit: Trail stop, time stop, session close, or risk halt.
    """

    def __init__(
        self,
        decision_service: DecisionService | None = None,
        exit_engine: ExitEngine | None = None,
        min_rr: float = 1.5,
        time_stop_bars: int = 60,
    ) -> None:
        self._decision_service = decision_service or DecisionService(min_rr=min_rr)
        self._exit_engine = exit_engine or ExitEngine(time_stop_bars=time_stop_bars)

    def on_bar(self, bar, auction, amt_dto: dict) -> None:
        """No per-bar state to update — the strategy is stateless."""
        pass

    def should_enter(self, ctx: DecisionContext) -> QuantDecision:
        """Evaluate entry using the DecisionService (gates 1-4 + signal builder)."""
        return self._decision_service.evaluate(ctx)

    @property
    def exit_engine(self) -> ExitEngine:
        """Access the exit engine for is_risk_free checks."""
        return self._exit_engine
