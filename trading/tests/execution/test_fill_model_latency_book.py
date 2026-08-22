"""Book-aware fill resolution + latency models (P1a).

``FillModel`` fills at the touch when a ``Depth`` book is provided (BUY at the
best ask, SELL at the best bid) and stamps fill timestamps through the
configured latency model. Defaults preserve the historical LTP-at-price,
zero-latency behavior.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain.enums import OrderSide, OrderType, TimeInForce
from tradex_domain.execution import OrderRequest
from tradex_domain.instruments import Equity
from tradex_domain.market import Depth
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.execution.fill_model import FillModel
from tradex_trading.execution.latency_models import (
    FixedLatencyModel,
    UniformLatencyModel,
    ZeroLatencyModel,
)

TS = datetime(2026, 8, 1, 9, 15, tzinfo=UTC)


def _request(side: OrderSide) -> OrderRequest:
    return OrderRequest(
        instrument=Equity.of("NSE", "RELIANCE"),
        side=side,
        order_type=OrderType.LIMIT,
        quantity=Quantity(value=Decimal("10")),
        price=Price(value=Decimal("100")),
        time_in_force=TimeInForce.DAY,
        reference_timestamp=TS,
    )


def _book(bid: str, ask: str) -> Depth:
    return Depth(
        instrument=Equity.of("NSE", "RELIANCE"),
        bids=((Price(value=Decimal(bid)), Quantity(value=Decimal("50"))),),
        asks=((Price(value=Decimal(ask)), Quantity(value=Decimal("50"))),),
        timestamp=TS,
    )


def test_buy_fills_at_best_ask_when_book_given() -> None:
    model = FillModel()
    fill = model.resolve_fill_price(_request(OrderSide.BUY), book=_book("99.5", "100.5"))
    assert fill.value == Decimal("100.5")


def test_sell_fills_at_best_bid_when_book_given() -> None:
    model = FillModel()
    fill = model.resolve_fill_price(_request(OrderSide.SELL), book=_book("99.5", "100.5"))
    assert fill.value == Decimal("99.5")


def test_market_price_used_when_no_book() -> None:
    """Without a book the historical LTP-at-price behavior is unchanged."""
    model = FillModel()
    assert model.resolve_fill_price(
        _request(OrderSide.BUY), market_price=Price(value=Decimal("101"))
    ).value == Decimal("101")


def test_slippage_applies_after_book_touch() -> None:
    class _Slippage:
        def apply(self, price, side, quantity) -> Price:
            return Price(value=price.value + Decimal("0.25"))

    model = FillModel(slippage_model=_Slippage())
    fill = model.resolve_fill_price(_request(OrderSide.BUY), book=_book("99.5", "100.5"))
    assert fill.value == Decimal("100.75")


def test_default_latency_is_zero() -> None:
    model = FillModel()
    assert model.fill_timestamp(_request(OrderSide.BUY)) == TS


def test_fixed_latency_delays_fill_timestamp() -> None:
    model = FillModel(latency_model=FixedLatencyModel(milliseconds=250))
    assert model.fill_timestamp(_request(OrderSide.BUY)) == TS + timedelta(milliseconds=250)


def test_uniform_latency_is_seed_reproducible() -> None:
    rng = random.Random(42)
    model = FillModel(latency_model=UniformLatencyModel(10, 50, rng=rng))
    t1 = model.fill_timestamp(_request(OrderSide.BUY))

    rng2 = random.Random(42)
    model2 = FillModel(latency_model=UniformLatencyModel(10, 50, rng=rng2))
    t2 = model2.fill_timestamp(_request(OrderSide.BUY))
    assert t1 == t2
    assert TS <= t1 <= TS + timedelta(milliseconds=50)


def test_zero_latency_model_is_identity() -> None:
    assert ZeroLatencyModel().apply(TS) == TS
