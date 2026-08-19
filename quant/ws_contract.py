"""WebSocket schema contract — typed definition of the WS snapshot shape.

This module defines the canonical schema for the WebSocket messages sent
from the backend to the frontend. The WSSnapshot dataclass mirrors the
output of view_state_to_ws() and can be used to:
1. Validate the snapshot shape in tests
2. Generate TypeScript types (future)
3. Document the contract between backend and frontend

The frontend TypeScript types in frontend/types.ts should stay in sync
with this schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WSPortfolio:
    """Portfolio state sent over WebSocket."""
    balance: float = 1_000_000.0
    equity: float = 1_000_000.0
    leverage: int = 10
    positions: list = field(default_factory=list)
    closedTrades: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "balance": self.balance,
            "equity": self.equity,
            "leverage": self.leverage,
            "positions": self.positions,
            "closedTrades": self.closedTrades,
        }


@dataclass(frozen=True)
class WSAgentDecision:
    """Agent decision projected from the deterministic quant decision."""
    direction: str = "FLAT"  # "LONG" | "SHORT" | "FLAT"
    modelLabel: str = ""
    regime: str = ""
    timing: str = ""
    sizeFraction: float = 0.0
    latencyUs: int = 0
    rationale: str = ""


@dataclass(frozen=True)
class WSSnapshot:
    """Canonical WebSocket snapshot shape.
    
    This is the contract between the backend and frontend. All fields
    are sent on every tick/snapshot. The frontend TypeScript types in
    frontend/types.ts (InstrumentState) should mirror this structure.
    
    Fields:
        _symbol: The instrument symbol
        portfolio: Account portfolio state
        amt: AMT analysis DTO (60-field dict from amt_result_to_dto)
        auction: Auction state from AuctionCoordinator
        quantDecision: The deterministic quant decision
        agentDecision: Projected agent decision for frontend display
        riskState: Session risk state
        tick: Current tick data
        ltp: Last traded price
        oi: Open interest
        depth: Order book depth (5-level)
    """
    _symbol: str
    portfolio: WSPortfolio | dict
    amt: dict | None = None
    auction: dict | None = None
    quantDecision: dict | None = None
    agentDecision: WSAgentDecision | dict | None = None
    riskState: dict | None = None
    tick: dict | None = None
    ltp: float = 0.0
    oi: int = 0
    depth: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to the dict shape expected by the frontend."""
        portfolio_dict = (
            self.portfolio.to_dict()
            if isinstance(self.portfolio, WSPortfolio)
            else self.portfolio
        )
        agent_dict = (
            {
                "direction": self.agentDecision.direction,
                "modelLabel": self.agentDecision.modelLabel,
                "regime": self.agentDecision.regime,
                "timing": self.agentDecision.timing,
                "sizeFraction": self.agentDecision.sizeFraction,
                "latencyUs": self.agentDecision.latencyUs,
                "rationale": self.agentDecision.rationale,
            }
            if isinstance(self.agentDecision, WSAgentDecision)
            else self.agentDecision
        )
        return {
            "_symbol": self._symbol,
            "portfolio": portfolio_dict,
            "amt": self.amt,
            "auction": self.auction,
            "quantDecision": self.quantDecision,
            "agentDecision": agent_dict,
            "riskState": self.riskState,
            "tick": self.tick,
            "ltp": self.ltp,
            "oi": self.oi,
            "depth": self.depth or {},
        }


# Expected keys in the WS snapshot — used for validation in tests.
WS_SNAPSHOT_KEYS = frozenset({
    "_symbol",
    "portfolio",
    "amt",
    "auction",
    "quantDecision",
    "agentDecision",
    "riskState",
    "tick",
    "ltp",
    "oi",
    "depth",
})

# Portfolio keys required by the frontend.
WS_PORTFOLIO_KEYS = frozenset({
    "balance",
    "equity",
    "leverage",
    "positions",
    "closedTrades",
})

# Agent decision keys projected from quant decision.
WS_AGENT_DECISION_KEYS = frozenset({
    "direction",
    "modelLabel",
    "regime",
    "timing",
    "sizeFraction",
    "latencyUs",
    "rationale",
})


def validate_ws_snapshot(snapshot: dict) -> list[str]:
    """Validate a WS snapshot dict has all required keys.
    
    Returns a list of missing keys (empty if valid).
    """
    missing = []
    for key in WS_SNAPSHOT_KEYS:
        if key not in snapshot:
            missing.append(key)
    return missing
