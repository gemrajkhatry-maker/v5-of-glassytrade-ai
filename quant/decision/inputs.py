"""DecisionInputs — bundles all inputs to DecisionContextBuilder.build().

The builder currently takes 15+ positional parameters. This dataclass
groups them into a single, self-documenting type that can be constructed
once in QuantEngine._decide() and passed through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionInputs:
    """All inputs needed to build a DecisionContext."""

    # Core
    bar: Any = None
    symbol: str = ""
    market: str = "NSE"
    contract_expiry: Any = None
    tick_size: float = 0.05

    # Timing
    bar_index: int = 0
    warm_bars: int = 15
    cooldown_remaining_sec: float = 0.0

    # Risk
    risk_state: Any = None

    # AMT analysis
    amt_dto: dict = field(default_factory=dict)
    order_book: Any = None
    interval_seconds: int = 60

    # Position
    position: Any = None
    entry_bar_index: int = 0
    recent_decisions: list | None = None
