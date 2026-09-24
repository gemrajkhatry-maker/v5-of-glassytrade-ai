"""State derivation tests — EventStore.fold() + project_state() + LiveQuoteCache.

Migrated from StateProjector (removed): the fold path is now the sole
position authority; LiveQuoteCache handles only per-tick live quotes.
"""

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.event_store import EventStore
from quant.events import (
    BarClosed,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.order import Fill, Order, Position
from quant.execution.risk import RiskState
from quant.state import LiveQuoteCache, ViewState, project_state
from quant.state_machine import EngineState


def _position(symbol="S", time="t1", size=10.0, entry=100.0):
    sig = Signal(type="LONG", reason="All 5 gates passed", entry=entry, sl=entry - 1,
                 tp=entry + 2, rr=2.0, model_label="Triple-A", symbol=symbol, timestamp=time)
    return Position(order=Order(signal=sig, quantity=size),
                    open_price=entry, open_time=time, size=size)


def _fold_view(store: EventStore) -> ViewState:
    return project_state(store.fold())


def test_fold_bar_sets_ltp():
    store = EventStore()
    store.append(BarClosed(symbol="S", time="t1",
                           bar=Bar(time="t1", open=100, high=101, low=99, close=100, volume=100)))
    v = _fold_view(store)
    assert v.ltp == 100.0


def test_fold_per_symbol_isolation():
    """Each symbol's EventStore produces independent state."""
    s1 = EventStore()
    s2 = EventStore()
    s1.append(BarClosed(symbol="S1", time="t",
                        bar=Bar(time="t", open=1, high=2, low=0.5, close=1.5, volume=10)))
    s2.append(BarClosed(symbol="S2", time="t",
                        bar=Bar(time="t", open=5, high=6, low=4, close=5.5, volume=10)))
    assert project_state(s1.fold()).ltp == 1.5
    assert project_state(s2.fold()).ltp == 5.5


def test_snapshot_defaults_empty_state():
    v = project_state(EngineState(symbol="S"))
    assert v.symbol == "S"
    assert v.tick is None
    assert v.ltp is None
    assert v.oi is None
    assert v.quant_decision is None
    # A fresh EngineState carries a default RiskState (state_machine
    # default_factory), so the fold path yields the default risk dict —
    # not None (None was the old StateProjector cache default).
    assert v.risk_state == {
        "halted": False,
        "haltReason": "",
        "consecutiveLosses": 0,
        "dailyPnl": 0.0,
        "tradesToday": 0,
        "equity": 1_000_000.0,
        "driftAlert": False,
        "driftMessage": "",
    }
    assert v.depth is None
    # Portfolio is always the full contract shape — the WS layer and React
    # reduce over balance/equity/positions unconditionally.
    assert v.portfolio == {
        "balance": 1_000_000.0,
        "equity": 1_000_000.0,
        "leverage": 10,
        "positions": [],
        "closedTrades": [],
    }
    assert v.amt is None


def test_bar_fold_sets_ohlc_tick():
    store = EventStore()
    store.append(BarClosed(symbol="S", time="t1",
                           bar=Bar(time="t1", open=100, high=101, low=99, close=100.5,
                                   volume=100, buy_volume=60, sell_volume=40, delta=20)))
    v = _fold_view(store)
    assert v.ltp == 100.5
    # Non-epoch bar times (test fixtures) pass through unchanged.
    assert v.tick == {
        "time": "t1",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 100.0,
        "vwap": 0.0,
        "takerBuyVolume": 60.0,
        "delta": 20.0,
        "barIntervalSec": 60,
    }


def test_bar_tick_time_normalized_to_iso_for_epoch():
    """Live gateway emits unix-epoch strings; the WS contract requires ISO."""
    store = EventStore()
    store.append(BarClosed(symbol="S", time="1786095001",
                           bar=Bar(time="1786095001", open=100, high=101, low=99,
                                   close=100.5, volume=100)))
    tick = _fold_view(store).tick
    assert tick["time"] == "2026-08-07T15:00:01+05:30"
    from datetime import datetime
    assert int(datetime.fromisoformat(tick["time"]).timestamp()) == 1786095001


def test_risk_fold():
    store = EventStore()
    store.append(RiskUpdated(symbol="S", time="t1",
                             risk=RiskState(daily_pnl=-50.0, consecutive_losses=2,
                                            halted=True, halt_reason="daily loss limit reached",
                                            risk_per_trade_pct=0.01,
                                            trades_today=3, equity=950000.0)))
    v = _fold_view(store)
    assert v.risk_state == {
        "halted": True,
        "haltReason": "daily loss limit reached",
        "consecutiveLosses": 2,
        "dailyPnl": -50.0,
        "tradesToday": 3,
        "equity": 950000.0,
        "driftAlert": False,
        "driftMessage": "",
    }


def test_quote_updates_ltp_oi_depth_per_tick():
    """Per-tick LTP/OI/depth refresh between bar closes (LiveQuoteCache)."""
    from quant.brokers.gateway import Tick

    cache = LiveQuoteCache()
    cache.on_quote("S", Tick(time="1", price=105.0, volume=0, oi=42.0,
                             depth={"bids": [{"price": 104.5, "quantity": 10}],
                                    "asks": [{"price": 105.5, "quantity": 8}]}))
    v = cache.snapshot("S")
    assert v.ltp == 105.0
    assert v.oi == 42.0
    assert v.depth == {"bids": [{"price": 104.5, "quantity": 10}],
                       "asks": [{"price": 105.5, "quantity": 8}]}
    cache.on_quote("S", Tick(time="2", price=106.0, volume=0, oi=43.0))
    v2 = cache.snapshot("S")
    assert v2.ltp == 106.0
    assert v2.oi == 43.0
    assert v2.depth is None


def test_portfolio_open_then_close():
    store = EventStore()
    pos = _position()
    store.append(PositionOpened(symbol="S", time="t1", position=pos))
    v = _fold_view(store)
    port = v.portfolio
    assert port["positions"][0]["id"] == pos._id
    assert port["positions"][0]["status"] == "OPEN"
    assert port["positions"][0]["entryPrice"] == 100.0
    assert port["positions"][0]["size"] == 10.0
    assert port["closedTrades"] == []

    store.append(PositionClosed(symbol="S", time="t2",
                                fill=Fill(position=pos, close_price=102.0,
                                          close_time="t2", reason="TP", pnl=20.0)))
    v2 = _fold_view(store)
    port2 = v2.portfolio
    assert port2["positions"] == []
    assert len(port2["closedTrades"]) == 1
    assert port2["closedTrades"][0]["id"] == pos._id
    assert port2["equity"] == 1_000_020.0


def test_portfolio_equity_reflects_realized_pnl():
    """After a winning trade, fold equity > INITIAL_CAPITAL."""
    store = EventStore()
    pos = _position(entry=100.0, size=10.0)
    store.append(PositionOpened(symbol="S", time="t0", position=pos))
    store.append(PositionClosed(
        symbol="S", time="t1",
        fill=Fill(position=pos, close_price=105.0, close_time="t1", reason="TP", pnl=50.0),
    ))
    v = _fold_view(store)
    assert v.portfolio["equity"] == 1_000_050.0


def test_live_cache_snapshot_defaults():
    """Empty LiveQuoteCache returns all-None ViewState."""
    v = LiveQuoteCache().snapshot("S")
    assert v.symbol == "S"
    assert v.tick is None
    assert v.ltp is None
    assert v.oi is None
    assert v.depth is None
