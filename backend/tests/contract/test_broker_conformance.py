from decimal import Decimal

import pytest

from glassytrade.adapters.brokers.dhan_gateway import DhanGateway
from glassytrade.adapters.brokers.paper_gateway import PaperGateway
from glassytrade.application.ports.broker import (
    BrokerCancelRequest,
    BrokerPlaceRequest,
)
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.execution.types import (
    Accepted,
    AmbiguousOutcome,
    BrokerLookupStatus,
    BrokerUnavailable,
    NotSent,
    OrderSide,
    Rejected,
    StatusUnavailable,
)

CONTRACT = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "sec-1")


def place_request(side: OrderSide = OrderSide.BUY, quantity: int = 2) -> BrokerPlaceRequest:
    return BrokerPlaceRequest(
        attempt_id="attempt-1",
        contract_id=CONTRACT,
        side=side,
        quantity=quantity,
        correlation_id="corr-1",
        reference_price=Decimal("100"),
    )


class FakeTransport:
    def __init__(self, *, place=None, cancel=None, lookup=None):
        self.place_response = place or {"status": "accepted", "broker_order_id": "dhan-1"}
        self.cancel_response = cancel or {"status": "accepted", "broker_order_id": "dhan-1"}
        self.lookup_response = lookup or {
            "status": "FOUND",
            "broker_order_id": "dhan-1",
            "intent_id": "intent-1",
            "filled_quantity": 0,
            "requested_quantity": 1,
        }
        self.orders = {}
        self.fills = []

    def place_order(self, request):
        response = self.place_response
        if isinstance(response, BaseException):
            raise response
        response = dict(response)
        self.orders[response.get("broker_order_id", "")] = {
            "broker_order_id": response.get("broker_order_id", ""),
            "intent_id": request.correlation_id,
            "status": response.get("status", "UNKNOWN"),
            "filled_quantity": response.get("filled_quantity", 0),
            "requested_quantity": request.quantity,
        }
        return response

    def cancel_order(self, request):
        response = dict(self.cancel_response)
        if isinstance(response, BaseException):
            raise response
        return response

    def replace_order(self, request):
        return self.place_response

    def get_order(self, broker_order_id):
        response = self.lookup_response
        if isinstance(response, BaseException):
            raise response
        return response

    def find_order_by_correlation(self, correlation_id):
        return self.get_order("dhan-1")

    def list_orders(self):
        return tuple(self.orders.values())

    def list_fills(self):
        return tuple(self.fills)

    def list_positions(self):
        return ()

    def stream_events(self):
        return iter(())


class OutageTransport(FakeTransport):
    def list_orders(self):
        raise BrokerUnavailable("broker down")


@pytest.mark.parametrize(
    "gateway_factory",
    [
        lambda transport: DhanGateway(transport),
        lambda transport: PaperGateway(transport=transport),
    ],
)
def test_accepted_rejected_and_not_sent_are_discriminated(gateway_factory):
    accepted = gateway_factory(FakeTransport())
    ack = accepted.place_order(place_request())
    assert isinstance(ack, Accepted)
    assert ack.broker_order_id

    rejected = gateway_factory(
        FakeTransport(place={"status": "rejected", "reason": "risk"})
    ).place_order(place_request())
    assert isinstance(rejected, Rejected)

    not_sent = gateway_factory(FakeTransport(place=TimeoutError("not sent"))).place_order(
        place_request()
    )
    assert isinstance(not_sent, (AmbiguousOutcome, StatusUnavailable, NotSent))


def test_timeout_after_acceptance_is_ambiguous_and_lookupable():
    transport = FakeTransport(place=TimeoutError("read timeout"))
    gateway = DhanGateway(transport)
    ack = gateway.place_order(place_request())
    assert isinstance(ack, AmbiguousOutcome)
    lookup = gateway.find_order_by_correlation("corr-1")
    assert lookup.status in {BrokerLookupStatus.FOUND, BrokerLookupStatus.UNAVAILABLE}


def test_paper_and_dhan_partial_fill_normalization_matches():
    dhan = DhanGateway(
        FakeTransport(
            place={
                "status": "accepted",
                "broker_order_id": "dhan-1",
                "filled_quantity": 1,
            },
            lookup={
                "status": "FOUND",
                "broker_order_id": "dhan-1",
                "intent_id": "intent-1",
                "filled_quantity": 1,
                "requested_quantity": 2,
            },
        )
    )
    paper = PaperGateway(fill_quantity=1)
    dhan_snapshot = dhan.get_order("dhan-1").order
    paper_snapshot = paper.get_order(paper.place_order(place_request()).broker_order_id).order
    assert dhan_snapshot.filled_quantity == paper_snapshot.filled_quantity == 1


def test_broker_outage_is_not_reported_as_empty_truth():
    gateway = DhanGateway(FakeTransport(lookup=BrokerUnavailable("broker down")))
    result = gateway.get_order("dhan-1")
    assert result.status is BrokerLookupStatus.UNAVAILABLE
    with pytest.raises(BrokerUnavailable):
        DhanGateway(OutageTransport()).list_orders()


def test_cancel_requires_a_finalized_request():
    gateway = PaperGateway()
    accepted = gateway.place_order(place_request())
    ack = gateway.cancel_order(
        BrokerCancelRequest(accepted.broker_order_id, "corr-1", "operator exit")
    )
    assert isinstance(ack, Accepted)
