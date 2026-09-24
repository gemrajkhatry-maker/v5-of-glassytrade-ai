"""Per-contract analysis worker with bounded mailbox and no trading authority."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Any

from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.market_data.events import MarketDataEvent


@dataclass(frozen=True)
class SymbolWorkerState:
    contract_id: ContractId
    running: bool
    processed: int
    dropped: int
    last_sequence: int | None
    errors: int


class SymbolWorker:
    def __init__(
        self,
        contract_id: ContractId,
        coordinator: Any,
        analyzer: Any,
        *,
        mailbox_capacity: int = 256,
    ) -> None:
        if mailbox_capacity <= 0:
            raise ValueError("mailbox_capacity must be positive")
        self.contract_id = contract_id
        self.coordinator = coordinator
        self.analyzer = analyzer
        self.mailbox: Queue[MarketDataEvent] = Queue(maxsize=mailbox_capacity)
        self._running = True
        self._processed = 0
        self._dropped = 0
        self._last_sequence: int | None = None
        self._errors = 0

    def offer(self, event: MarketDataEvent) -> bool:
        if event.contract_id != self.contract_id or not self._running:
            self._dropped += 1
            return False
        if self._last_sequence is not None and event.sequence_number <= self._last_sequence:
            self._dropped += 1
            return False
        try:
            self.mailbox.put_nowait(event)
        except Full:
            self._dropped += 1
            return False
        return True

    on_market_data = offer

    def start(self) -> None:
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                event = self.mailbox.get_nowait()
            except Empty:
                break
            try:
                intent = self.analyzer.decide(self.contract_id, event)
                if intent is not None:
                    self.coordinator.submit_entry(intent)
                self._last_sequence = event.sequence_number
                self._processed += 1
            except Exception:
                self._errors += 1
            finally:
                self.mailbox.task_done()

    def stop(self) -> None:
        self._running = False

    def worker_state(self) -> SymbolWorkerState:
        return SymbolWorkerState(
            contract_id=self.contract_id,
            running=self._running,
            processed=self._processed,
            dropped=self._dropped,
            last_sequence=self._last_sequence,
            errors=self._errors,
        )
