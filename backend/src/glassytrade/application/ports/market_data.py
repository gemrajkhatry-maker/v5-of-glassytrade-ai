"""Market-data feed port."""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.market_data.events import MarketDataEvent


class MarketDataPort(Protocol):
    def subscribe(self, contract_ids: tuple[ContractId, ...]) -> None: ...

    def unsubscribe(self, contract_ids: tuple[ContractId, ...]) -> None: ...

    def stream(self) -> AsyncIterator[MarketDataEvent]: ...

    def close(self) -> None: ...
