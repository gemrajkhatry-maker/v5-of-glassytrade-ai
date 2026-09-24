"""Full-identity three-way reconciliation for startup recovery."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from glassytrade.domain.execution.types import BrokerCapabilities
from glassytrade.domain.ledger.events import LedgerEvent


@dataclass(frozen=True)
class ReconciliationRequest:
    ledger_events: tuple[LedgerEvent, ...]
    oms_positions: tuple[Mapping[str, Any], ...]
    broker_positions: tuple[Mapping[str, Any], ...]
    broker_available: bool
    broker_capabilities: BrokerCapabilities | None = None


@dataclass(frozen=True)
class ReconciliationCase:
    discrepancy: str
    contract_id: str
    expected_state: Mapping[str, Any]
    observed_state: Mapping[str, Any]


@dataclass(frozen=True)
class ReconciliationReport:
    accepting_orders: bool
    has_quantity_mismatch: bool
    broker_snapshot_available: bool
    discrepancies: tuple[str, ...]
    cases: tuple[ReconciliationCase, ...]


class ReconciliationService:
    def compare(self, request: ReconciliationRequest) -> ReconciliationReport:
        if not request.broker_available:
            return ReconciliationReport(
                accepting_orders=False,
                has_quantity_mismatch=False,
                broker_snapshot_available=False,
                discrepancies=("broker_snapshot_unavailable",),
                cases=(),
            )

        local = self._by_contract(request.oms_positions)
        broker = self._by_contract(request.broker_positions)
        discrepancies: list[str] = []
        cases: list[ReconciliationCase] = []
        has_quantity_mismatch = False

        for contract_id in sorted(set(local) | set(broker)):
            expected = local.get(contract_id)
            observed = broker.get(contract_id)
            if expected is None:
                discrepancy = "broker_only_position"
                cases.append(ReconciliationCase(discrepancy, contract_id, {}, observed or {}))
                discrepancies.append(discrepancy)
                continue
            if observed is None:
                discrepancy = "oms_only_position"
                cases.append(ReconciliationCase(discrepancy, contract_id, expected, {}))
                discrepancies.append(discrepancy)
                continue
            mismatches = self._mismatches(expected, observed)
            if mismatches:
                has_quantity_mismatch = has_quantity_mismatch or "quantity" in mismatches
                discrepancy = "identity_mismatch:" + ",".join(mismatches)
                discrepancies.append(discrepancy)
                cases.append(ReconciliationCase(discrepancy, contract_id, expected, observed))

        return ReconciliationReport(
            accepting_orders=not discrepancies,
            has_quantity_mismatch=has_quantity_mismatch,
            broker_snapshot_available=True,
            discrepancies=tuple(discrepancies),
            cases=tuple(cases),
        )

    @staticmethod
    def _by_contract(positions: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
        result = {}
        for position in positions:
            contract_id = str(position.get("contract_id", position.get("contract", "")))
            if contract_id:
                result[contract_id] = dict(position)
        return result

    @staticmethod
    def _mismatches(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> tuple[str, ...]:
        mismatches: list[str] = []
        expected_qty = int(expected.get("signed_quantity", 0))
        observed_qty = int(observed.get("signed_quantity", 0))
        if expected_qty != observed_qty:
            mismatches.append("quantity")
        if str(expected.get("side", "")) != str(observed.get("side", "")):
            mismatches.append("side")
        expected_price = Decimal(str(expected.get("average_entry", "0")))
        observed_price = Decimal(str(observed.get("average_entry", "0")))
        if abs(expected_price - observed_price) > Decimal("0.0001"):
            mismatches.append("average_price")
        if str(expected.get("state", "")) != str(observed.get("state", "")):
            mismatches.append("state")
        return tuple(mismatches)
