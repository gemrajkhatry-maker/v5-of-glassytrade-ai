"""Tests for fill sources — BrokerFillSource, PaperFillSource, SimulatedFillSource."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from tradex_domain.enums import OrderSide, OrderStatus, OrderType, ProductType, TimeInForce
from tradex_domain.execution import OrderRequest
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.execution.fill_sources import (
    BrokerFillSource,
    PaperFillSource,
    SimulatedFillSource,
)


def _make_request(
    price: Decimal | None = None,
    quantity: Decimal = Decimal("10"),
) -> OrderRequest:
    return OrderRequest(
        instrument=Equity.of("NSE", "RELIANCE"),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT if price else OrderType.MARKET,
        quantity=Quantity(value=quantity),
        price=Price(value=price) if price else None,
        time_in_force=TimeInForce.DAY,
        product_type=ProductType.INTRADAY,
    )


class TestSimulatedFillSource:
    """SimulatedFillSource fills at request price; rejects price-less orders."""

    def test_fill_at_limit_price(self) -> None:
        fill_source = SimulatedFillSource()
        req = _make_request(price=Decimal("2500.00"))
        order, fill = fill_source.submit(req)
        assert order.status == OrderStatus.FILLED
        assert fill is not None
        assert fill.price.value == Decimal("2500.00")

    def test_price_less_market_order_raises(self) -> None:
        """A zero-priced fill silently corrupts P&L (avg_price=0) and breaks
        FeeCalculator — SimulatedFillSource must fail loudly instead."""
        fill_source = SimulatedFillSource()
        req = _make_request()  # MARKET, no price
        with pytest.raises(ValueError, match="without a positive price"):
            fill_source.submit(req)

    def test_fill_uses_trigger_price_as_fallback(self) -> None:
        fill_source = SimulatedFillSource()
        req = OrderRequest(
            instrument=Equity.of("NSE", "RELIANCE"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Quantity(value=Decimal("10")),
            price=None,
            trigger_price=Price(value=Decimal("100.50")),
            time_in_force=TimeInForce.DAY,
            product_type=ProductType.INTRADAY,
        )
        order, fill = fill_source.submit(req)
        assert fill is not None
        assert fill.price.value == Decimal("100.50")


class TestPaperFillSource:
    """PaperFillSource fills at LTP, request price, or nominal."""

    def test_price_less_market_order_raises(self) -> None:
        """PaperFillSource must reject price-less MARKET orders just like
        SimulatedFillSource — a zero-priced fill corrupts P&L."""
        fill_source = PaperFillSource()
        req = _make_request()  # MARKET, no price
        with pytest.raises(ValueError, match="without a positive price"):
            fill_source.submit(req)

    def test_fill_at_request_price(self) -> None:
        fill_source = PaperFillSource()
        req = _make_request(price=Decimal("3000.00"))
        order, fill = fill_source.submit(req)
        assert fill is not None
        assert fill.price.value == Decimal("3000.00")

    def test_delegates_to_book_source_when_depth_available(self) -> None:
        """With a live L2 book, paper matches against it (sweep) instead of LTP."""
        from datetime import UTC, datetime

        from tradex_domain.market import Depth

        from tradex_trading.execution.book_fill_source import BookFillSource

        inst = Equity.of("NSE", "RELIANCE")
        book = BookFillSource()
        book.update_depth(
            Depth(
                instrument=inst,
                bids=((Price(value=Decimal("2999")), Quantity(value=Decimal("50"))),),
                asks=((Price(value=Decimal("3000")), Quantity(value=Decimal("50"))),),
                timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
            )
        )
        fill_source = PaperFillSource(book_source=book)
        req = _make_request(price=Decimal("3000.00"))

        order, fill = fill_source.submit(req)

        assert fill is not None
        assert fill.price.value == Decimal("3000.00")  # swept at the best ask
        assert order.status is OrderStatus.FILLED

    def test_falls_back_to_ltp_without_book(self) -> None:
        """No book for the instrument → historical LTP-at-price behavior."""
        from tradex_trading.execution.book_fill_source import BookFillSource

        fill_source = PaperFillSource(book_source=BookFillSource())
        req = _make_request(price=Decimal("3000.00"))

        order, fill = fill_source.submit(req)

        assert fill is not None
        assert fill.price.value == Decimal("3000.00")


class TestBrokerFillSource:
    """BrokerFillSource delegates to broker adapter's submit_order."""

    def test_calls_submit_order(self) -> None:
        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = "order-123"
        fill_source = BrokerFillSource(mock_broker)

        req = _make_request(price=Decimal("2500.00"))
        order, fill = fill_source.submit(req)

        mock_broker.submit_order.assert_called_once_with(req)
        assert order.status == OrderStatus.ACK
        assert fill is None

    def test_does_not_call_place_order(self) -> None:
        """BrokerFillSource must NOT call place_order (old bug)."""
        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = "order-123"
        fill_source = BrokerFillSource(mock_broker)

        req = _make_request(price=Decimal("2500.00"))
        fill_source.submit(req)

        mock_broker.place_order.assert_not_called()

    def test_fallback_when_no_submit_order(self) -> None:
        """If broker has no submit_order, returns ACK order."""
        plain_broker = object()  # no submit_order method
        fill_source = BrokerFillSource(plain_broker)

        req = _make_request(price=Decimal("2500.00"))
        order, fill = fill_source.submit(req)
        assert order.status == OrderStatus.ACK
        assert fill is None
