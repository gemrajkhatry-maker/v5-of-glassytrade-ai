"""Tests for the position-sizing seam (Sizer)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import (
    Candle,
    Equity,
    FixedSizer,
    OHLC,
    OrderSide,
    Price,
    Quantity,
    Signal,
    SignalStrengthSizer,
    Timeframe,
)
from tradex_domain.events import PlaceOrderCommand

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.strategy.core.engine import ReactiveStrategyEngine


def _instrument() -> Equity:
    return Equity.of("NSE", "RELIANCE")


def _signal(strength: float) -> Signal:
    return Signal(
        instrument=_instrument(),
        direction=OrderSide.BUY,
        strength=strength,
        reason="test",
    )


def _candle() -> Candle:
    return Candle(
        instrument=_instrument(),
        timeframe=Timeframe.D1,
        ohlc=OHLC(
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100")),
        ),
        volume=Quantity(Decimal("10")),
        timestamp=datetime(2026, 8, 14, 9, 15, tzinfo=UTC),
    )


class _ReturningStrategy:
    strategy_id = "sizer-test"

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    def on_bar(self, context, bar):  # pragma: no cover - trivial
        return self._signal

    def on_quote(self, context, quote):  # pragma: no cover - trivial
        return None

    def on_fill(self, context, fill):  # pragma: no cover - trivial
        pass


class TestSizers:
    def test_signal_strength_sizer_preserves_legacy(self) -> None:
        sizer = SignalStrengthSizer()
        assert sizer.size(_signal(0.7)).value == Decimal("0.7")
        # Zero/absent strength falls back to a single unit (legacy behavior).
        assert sizer.size(_signal(0.0)).value == Decimal("1.0")

    def test_fixed_sizer_ignores_strength(self) -> None:
        sizer = FixedSizer(Decimal("5"))
        assert sizer.size(_signal(999.0)).value == Decimal("5")


class TestEngineUsesSizer:
    def test_fixed_sizer_drives_order_quantity(self) -> None:
        bus = ReactiveBus()
        commands: list[PlaceOrderCommand] = []
        bus.of_type(PlaceOrderCommand).subscribe(commands.append)

        engine = ReactiveStrategyEngine(
            bus,
            fill_reference="signal_close",
            sizer=FixedSizer(Decimal("3")),
        )
        engine.register(_ReturningStrategy(_signal(50.0)))

        bus.publish(_candle())

        assert len(commands) == 1
        assert commands[0].request.quantity.value == Decimal("3")
