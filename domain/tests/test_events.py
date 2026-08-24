"""Tests for domain event timestamp derivation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain.enums import OrderSide, OrderStatus, OrderType, Timeframe, TimeInForce
from tradex_domain.events import CandleReceived, OrderFilled, OrderPlaced
from tradex_domain.execution import Fill, Order
from tradex_domain.instruments import Equity
from tradex_domain.market import Candle, OHLC
from tradex_domain.value_objects import OrderId, Price, Quantity


def _eq() -> Equity:
    return Equity.of("NSE", "RELIANCE")


def test_order_filled_derives_market_timestamp() -> None:
    market_ts = datetime(2026, 8, 14, 9, 15, tzinfo=UTC)
    fill = Fill(
        order_id=OrderId(value="o1"),
        instrument=_eq(),
        side=OrderSide.BUY,
        quantity=Quantity(Decimal("10")),
        price=Price(Decimal("100")),
        timestamp=market_ts,
    )
    assert OrderFilled(fill=fill).timestamp == market_ts


def test_candle_received_derives_candle_timestamp() -> None:
    ts = datetime(2026, 8, 14, 9, 15, tzinfo=UTC)
    candle = Candle(
        instrument=_eq(),
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(Decimal("1")),
            high=Price(Decimal("2")),
            low=Price(Decimal("0.5")),
            close=Price(Decimal("1.5")),
        ),
        volume=Quantity(Decimal("10")),
        timestamp=ts,
    )
    assert CandleReceived(candle=candle).timestamp == ts


def test_event_without_timestamped_payload_falls_back() -> None:
    order = Order(
        order_id=OrderId(value="o1"),
        instrument=_eq(),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(Decimal("1")),
        price=None,
        time_in_force=TimeInForce.DAY,
        status=OrderStatus.NEW,
    )
    assert isinstance(OrderPlaced(order=order).timestamp, datetime)
