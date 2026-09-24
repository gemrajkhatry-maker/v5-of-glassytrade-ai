"""Normalized Dhan gateway boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from glassytrade.application.ports.broker import (
    BrokerCancelRequest,
    BrokerLookupResult,
    BrokerPlaceRequest,
    BrokerReplaceRequest,
)
from glassytrade.domain.execution.types import (
    Accepted,
    AmbiguousOutcome,
    BrokerCapabilities,
    BrokerFill,
    BrokerLookupStatus,
    BrokerOrderSnapshot,
    BrokerUnavailable,
    NotSent,
    Rejected,
    StatusUnavailable,
)


class DhanGateway:
    capabilities = BrokerCapabilities(
        frozenset({"native_stop", "order_lookup", "fills", "replace", "cancel"})
    )

    def __init__(self, transport: Any) -> None:
        self.transport = transport

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _error_reason(error: BaseException) -> str:
        return str(error) or error.__class__.__name__

    def _ack(self, response: Any, attempt_id: str, correlation_id: str):
        if isinstance(response, BaseException):
            if isinstance(response, (TimeoutError, ConnectionError)):
                return AmbiguousOutcome(self._error_reason(response), correlation_id)
            if isinstance(response, BrokerUnavailable):
                return StatusUnavailable(self._error_reason(response), correlation_id)
            return NotSent(self._error_reason(response), attempt_id)
        if not isinstance(response, dict):
            return NotSent("broker returned a malformed response", attempt_id)
        status = str(response.get("status", "UNKNOWN")).upper()
        if status in {"ACCEPTED", "OPEN", "WORKING"}:
            return Accepted(
                attempt_id,
                str(response.get("broker_order_id", response.get("orderId", ""))),
                self._now(),
            )
        if status in {"REJECTED", "REJECT"}:
            return Rejected(attempt_id, str(response.get("reason", "rejected")))
        if status in {"NOT_SENT", "INVALID"}:
            return NotSent(str(response.get("reason", "not sent")), attempt_id)
        if status in {"UNAVAILABLE", "STATUS_UNAVAILABLE"}:
            return StatusUnavailable(str(response.get("reason", "status unavailable")))
        return AmbiguousOutcome(str(response.get("reason", "unknown broker outcome")), correlation_id)

    def place_order(self, request: BrokerPlaceRequest):
        try:
            response = self.transport.place_order(request)
        except Exception as exc:
            response = exc
        return self._ack(response, request.attempt_id, request.correlation_id)

    def cancel_order(self, request: BrokerCancelRequest):
        try:
            response = self.transport.cancel_order(request)
        except Exception as exc:
            response = exc
        attempt_id = f"cancel:{request.correlation_id}"
        return self._ack(response, attempt_id, request.correlation_id)

    def replace_order(self, request: BrokerReplaceRequest):
        try:
            response = self.transport.replace_order(request)
        except Exception as exc:
            response = exc
        attempt_id = f"replace:{request.correlation_id}"
        return self._ack(response, attempt_id, request.correlation_id)

    @staticmethod
    def _snapshot(value: Any, broker_order_id: str, intent_id: str = "") -> BrokerOrderSnapshot:
        if not isinstance(value, dict):
            raise BrokerUnavailable("broker returned a malformed order snapshot")
        return BrokerOrderSnapshot(
            broker_order_id=str(value.get("broker_order_id", value.get("orderId", broker_order_id))),
            intent_id=str(value.get("intent_id", value.get("correlation_id", intent_id))),
            status=str(value.get("status", "UNKNOWN")),
            filled_quantity=int(value.get("filled_quantity", value.get("cumulative_filled_quantity", 0))),
            requested_quantity=int(value.get("requested_quantity", value.get("quantity", 1))),
        )

    def get_order(self, broker_order_id: str) -> BrokerLookupResult:
        try:
            response = self.transport.get_order(broker_order_id)
        except Exception as exc:
            return BrokerLookupResult(BrokerLookupStatus.UNAVAILABLE, reason=str(exc))
        if isinstance(response, dict) and str(response.get("status", "")).upper() == "UNAVAILABLE":
            return BrokerLookupResult(BrokerLookupStatus.UNAVAILABLE, reason=str(response.get("reason", "unavailable")))
        if isinstance(response, dict) and str(response.get("status", "")).upper() == "CONFIRMED_ABSENT":
            return BrokerLookupResult(BrokerLookupStatus.CONFIRMED_ABSENT)
        try:
            return BrokerLookupResult(
                BrokerLookupStatus.FOUND,
                self._snapshot(response, broker_order_id),
            )
        except (BrokerUnavailable, ValueError) as exc:
            return BrokerLookupResult(BrokerLookupStatus.UNAVAILABLE, reason=str(exc))

    def find_order_by_correlation(self, correlation_id: str) -> BrokerLookupResult:
        try:
            response = self.transport.find_order_by_correlation(correlation_id)
        except Exception as exc:
            return BrokerLookupResult(BrokerLookupStatus.UNAVAILABLE, reason=str(exc))
        if isinstance(response, dict) and str(response.get("status", "")).upper() in {"CONFIRMED_ABSENT", "UNAVAILABLE"}:
            return BrokerLookupResult(
                BrokerLookupStatus(response["status"]),
                reason=response.get("reason"),
            )
        try:
            return BrokerLookupResult(
                BrokerLookupStatus.FOUND,
                self._snapshot(response, "", correlation_id),
            )
        except (BrokerUnavailable, ValueError) as exc:
            return BrokerLookupResult(BrokerLookupStatus.UNAVAILABLE, reason=str(exc))

    def list_orders(self) -> tuple[BrokerOrderSnapshot, ...]:
        response = self.transport.list_orders()
        if response is None:
            raise BrokerUnavailable("broker order snapshot unavailable")
        return tuple(self._snapshot(item, str(index)) for index, item in enumerate(response))

    def list_fills(self) -> tuple[BrokerFill, ...]:
        response = self.transport.list_fills()
        if response is None:
            raise BrokerUnavailable("broker fill snapshot unavailable")
        return tuple(
            BrokerFill(
                broker_fill_id=str(item["broker_fill_id"]),
                broker_order_id=str(item["broker_order_id"]),
                intent_id=str(item.get("intent_id", "")),
                quantity=int(item["quantity"]),
                price=Decimal(str(item["price"])),
                fees=Decimal(str(item.get("fees", "0"))),
                filled_at=item["filled_at"],
                cumulative_filled_quantity=int(item.get("cumulative_filled_quantity", 0)),
            )
            for item in response
        )

    def list_positions(self) -> tuple[object, ...]:
        response = self.transport.list_positions()
        if response is None:
            raise BrokerUnavailable("broker position snapshot unavailable")
        return tuple(response)

    async def stream_events(self):
        stream = self.transport.stream_events()
        if hasattr(stream, "__aiter__"):
            async for event in stream:
                yield event
        else:
            for event in stream:
                yield event
