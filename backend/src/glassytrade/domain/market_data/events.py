"""Canonical normalized market-data event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.common.money import to_decimal
from glassytrade.domain.common.provenance import EvidenceQuality

EventType = Literal["LTP", "QUOTE", "DEPTH", "TRADE", "STATUS"]


@dataclass(frozen=True)
class MarketDataEvent:
    event_id: str
    contract_id: ContractId
    exchange_timestamp: datetime
    received_timestamp: datetime
    sequence_number: int
    event_type: str
    price: Decimal
    size: int
    side: str | None
    provenance: EvidenceQuality
    source: str = "unknown"
    bid: Decimal | None = None
    ask: Decimal | None = None
    cumulative_volume: int | None = None
    quality: EvidenceQuality | None = None
    correction_state: str = "NONE"

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must be non-empty")
        if not isinstance(self.contract_id, ContractId):
            raise TypeError("contract_id must be ContractId")
        if self.sequence_number < 0:
            raise ValueError("sequence_number must be non-negative")
        if self.exchange_timestamp.tzinfo is None or self.received_timestamp.tzinfo is None:
            raise ValueError("market-data timestamps must be timezone-aware")
        if not self.event_type.strip():
            raise ValueError("event_type must be non-empty")
        object.__setattr__(self, "price", to_decimal(self.price))
        if self.price < 0:
            raise ValueError("price must be non-negative")
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 0:
            raise ValueError("size must be a non-negative integer")
        if self.side is not None and self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY, SELL, or None")
        object.__setattr__(self, "provenance", EvidenceQuality(self.provenance))
        if self.quality is not None:
            object.__setattr__(self, "quality", EvidenceQuality(self.quality))
        for name in ("bid", "ask"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, to_decimal(value))
                if getattr(self, name) < 0:
                    raise ValueError(f"{name} must be non-negative")
        if self.cumulative_volume is not None and (
            not isinstance(self.cumulative_volume, int)
            or isinstance(self.cumulative_volume, bool)
            or self.cumulative_volume < 0
        ):
            raise ValueError("cumulative_volume must be a non-negative integer")

    @property
    def effective_quality(self) -> EvidenceQuality:
        return self.quality or self.provenance
