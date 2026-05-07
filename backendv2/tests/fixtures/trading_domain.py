"""Shared fixtures for domain-level tests."""
import pytest
from decimal import Decimal

from app.domain.trading.model.value_objects import (
    OHLC, AMTResult, AggressivePrint, OrderBook, OrderBookLevel,
    VolumeProfileLevel, FootprintCandle, FootprintLevel
)


@pytest.fixture
def ohlc_tick():
    """Single OHLC candle."""
    return OHLC.create(
        time="2024-01-01T09:15:00",
        open=100.0, high=101.0, low=99.5, close=100.8,
        volume=500, delta=200
    )


@pytest.fixture
def ohlc_data_60():
    """60 candles of realistic uptrend data."""
    candles = []
    for i in range(60):
        price = 100.0 + i * 0.3
        candles.append(OHLC.create(
            time=f"2024-01-01T09:{15 + i % 60:02d}:00",
            open=price, high=price + 0.5, low=price - 0.2,
            close=price + 0.3, volume=120, delta=30
        ))
    return candles


@pytest.fixture
def ohlc_data_flat():
    """20 candles of flat/balanced data."""
    candles = []
    for i in range(20):
        candles.append(OHLC.create(
            time=f"2024-01-01T09:{15 + i:02d}:00",
            open=100.0, high=100.5, low=99.5, close=100.0,
            volume=50, delta=0
        ))
    return candles


@pytest.fixture
def amt_result_balanced():
    """Balanced market state AMT result."""
    return AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=102.0,
        value_area_low=98.0,
        cvd_slope=0.3,
        session_vwap=100.5,
        vwap_upper_2=103.0,
        vwap_lower_2=97.0,
        aggressive_prints=(
            AggressivePrint(price=99.5, time="t1", side="BUY", volume=100, delta=50),
        ),
        aggression=3.0,
        ib_high=101.5,
        ib_low=99.0,
        profile_shape="b",
    )


@pytest.fixture
def amt_result_imbalanced():
    """Imbalanced market state AMT result."""
    return AMTResult(
        market_state="IMBALANCED",
        poc=100.0,
        value_area_high=103.0,
        value_area_low=98.0,
        cvd_slope=0.8,
        session_vwap=100.5,
        aggressive_prints=(
            AggressivePrint(price=102.5, time="t1", side="BUY", volume=200, delta=150),
        ),
        aggression=5.0,
        break_direction="UP",
        ib_high=101.5,
        ib_low=99.0,
        profile_shape="b",
    )


@pytest.fixture
def order_book_tight():
    """Tight spread order book."""
    return OrderBook(
        bids=(
            OrderBookLevel(price=100.75, quantity=50),
            OrderBookLevel(price=100.70, quantity=100),
        ),
        asks=(
            OrderBookLevel(price=100.80, quantity=50),
            OrderBookLevel(price=100.85, quantity=100),
        ),
    )


@pytest.fixture
def order_book_wide():
    """Wide spread order book."""
    return OrderBook(
        bids=(
            OrderBookLevel(price=100.50, quantity=30),
            OrderBookLevel(price=100.40, quantity=60),
        ),
        asks=(
            OrderBookLevel(price=101.20, quantity=30),
            OrderBookLevel(price=101.30, quantity=60),
        ),
    )


def make_ohlc_series(n=60, start_price=100.0, trend=0.3, volatility=0.5):
    """Helper to create OHLC series with optional trend."""
    candles = []
    price = start_price
    for i in range(n):
        candles.append(OHLC.create(
            time=f"2024-01-01T{9 + i // 60:02d}:{i % 60:02d}:00",
            open=price,
            high=price + volatility,
            low=price - volatility * 0.4,
            close=price + trend,
            volume=120,
            delta=30
        ))
        price += trend
    return candles
