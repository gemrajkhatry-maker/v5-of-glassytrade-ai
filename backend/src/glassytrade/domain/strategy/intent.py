"""Strategy outputs before risk sizing and OMS ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.common.money import to_decimal


@dataclass(frozen=True)
class EntryIntent:
    intent_id: str
    contract_id: ContractId
    side: str
    desired_quantity: int
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    setup: str
    evidence_ids: tuple[str, ...] = ()
    expires_at: datetime | None = None
    mode: str = "paper"

    def __post_init__(self) -> None:
        if not self.intent_id.strip() or not self.setup.strip():
            raise ValueError("intent_id and setup must be non-empty")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("entry side must be BUY or SELL")
        if not isinstance(self.desired_quantity, int) or self.desired_quantity <= 0:
            raise ValueError("desired_quantity must be a positive integer")
        for name in ("entry_price", "stop_price", "target_price"):
            value = to_decimal(getattr(self, name))
            object.__setattr__(self, name, value)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.mode not in {"paper", "live"}:
            raise ValueError("mode must be paper or live")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")


@dataclass(frozen=True)
class ExitIntent:
    intent_id: str
    position_id: str
    contract_id: ContractId
    side: str
    quantity: int
    reason: str
    mode: str = "paper"

    def __post_init__(self) -> None:
        if not self.intent_id.strip() or not self.position_id.strip():
            raise ValueError("intent_id and position_id must be non-empty")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("exit side must be BUY or SELL")
        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        if not self.reason.strip():
            raise ValueError("exit reason must be non-empty")
        if self.mode not in {"paper", "live"}:
            raise ValueError("mode must be paper or live")
