"""Tests for OrderflowStore persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain.enums import OrderSide, Timeframe
from tradex_domain.instruments import Equity
from tradex_domain.market import OHLC
from tradex_domain.strategy import Signal
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.analytics.orderflow_types import FootprintLevel, OrderflowCandle, VolumeProfile
from tradex_trading.datalake.orderflow_store import OrderflowStore

INSTRUMENT = Equity.of("NSE", "RELIANCE")
T0 = datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC)


def _candle() -> OrderflowCandle:
    return OrderflowCandle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100.5")),
        ),
        volume=Quantity(Decimal("300")),
        timestamp=T0,
        buy_volume=200.0,
        sell_volume=100.0,
        tick_count=3,
        footprint={100.0: FootprintLevel(100.0, bid_volume=50, ask_volume=150)},
    )


def test_candle_round_trip(tmp_path) -> None:
    with OrderflowStore(tmp_path / "of.db") as store:
        store.insert_candle(_candle())
        rows = store.recent_candles(str(INSTRUMENT), Timeframe.M1)
        assert len(rows) == 1
        ts, o, h, lo, c, vol, buy, sell, ticks = rows[0]
        assert (o, h, lo, c) == (100.0, 101.0, 99.0, 100.5)
        assert (vol, buy, sell, ticks) == (300.0, 200.0, 100.0, 3)
        assert ts == T0.isoformat()


def test_volume_profile_round_trip(tmp_path) -> None:
    vp = VolumeProfile(
        session_date="2026-08-08",
        poc=100.0,
        vah=102.0,
        val=98.0,
        total_volume=1000.0,
        lvn_levels=(99.0,),
        shape="p_shape",
        poc_position_pct=0.8,
        volume_at_price={100.0: 500.0, 101.0: 300.0},
    )
    with OrderflowStore(tmp_path / "of.db") as store:
        store.insert_volume_profile(str(INSTRUMENT), vp)
        profiles = store.recent_profiles(str(INSTRUMENT))
        assert len(profiles) == 1
        got = profiles[0]
        assert got.poc == 100.0 and got.shape == "p_shape"
        assert got.volume_at_price == {100.0: 500.0, 101.0: 300.0}


def test_signal_round_trip(tmp_path) -> None:
    sig = Signal(
        instrument=INSTRUMENT,
        direction=OrderSide.BUY,
        strength=72.0,
        reason="absorption",
        metadata={"delta": 1200.0},
        timestamp=T0,
    )
    with OrderflowStore(tmp_path / "of.db") as store:
        store.insert_signal(str(INSTRUMENT), sig)
        assert store.recent_signal_reasons(str(INSTRUMENT)) == ["absorption"]


def test_disconnected_store_raises(tmp_path) -> None:
    store = OrderflowStore(tmp_path / "of.db")
    try:
        store.insert_candle(_candle())
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError for disconnected store")
