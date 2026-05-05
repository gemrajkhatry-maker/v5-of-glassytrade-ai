"""Tests for CandlePipeline — OHLC candle building from ticks."""

from app.runtime.pipeline.events import NormalizedTick, Candle, CandleTimeframe
from app.runtime.pipeline.candle_builder import CandlePipeline


def _make_tick(symbol="BANKNIFTY", price=45000.0, volume=100, ts=1000.0, bid=44999.0, ask=45001.0, bv=50, av=50):
    return NormalizedTick(
        symbol=symbol, price=price, volume=volume, timestamp=ts,
        bid=bid, ask=ask, bid_volume=bv, ask_volume=av,
        sequence=1, tick_size=0.05, lot_size=1, multiplier=1.0,
    )


def test_empty_pipeline_no_candles():
    p = CandlePipeline()
    result = p.build_candles([])
    assert result == {}


def test_single_tick_creates_active_candle():
    p = CandlePipeline()
    tick = _make_tick(price=45000.0, ts=0)
    candles = p.process(tick)
    active = p.get_active("BANKNIFTY")
    assert active is not None
    assert active.open == 45000.0
    assert active.high == 45000.0
    assert active.low == 45000.0
    assert active.volume == 100


def test_multiple_ticks_update_candle():
    p = CandlePipeline()
    p.process(_make_tick(price=45000.0, ts=0))
    p.process(_make_tick(price=45010.0, volume=200, ts=1))
    p.process(_make_tick(price=44990.0, volume=50, ts=2))
    active = p.get_active("BANKNIFTY")
    assert active.open == 45000.0
    assert active.high == 45010.0
    assert active.low == 44990.0
    assert active.close == 44990.0
    assert active.volume == 350


def test_new_minute_emits_completed_candle():
    p = CandlePipeline()
    # Minute 0
    p.process(_make_tick(price=45000.0, ts=0))
    p.process(_make_tick(price=45010.0, ts=30_000_000_000))
    # Minute 1 (60s later in ns)
    emitted = p.process(_make_tick(price=45020.0, ts=60_000_000_000))
    assert len(emitted) == 1
    completed = emitted[0]
    assert completed.symbol == "BANKNIFTY"
    assert completed.timeframe == CandleTimeframe.M1
    assert completed.open == 45000.0
    assert completed.high == 45010.0
    assert completed.low == 45000.0
    assert completed.close == 45010.0
    assert completed.volume == 200


def test_reset_clears_state():
    p = CandlePipeline()
    p.process(_make_tick(price=45000.0, ts=0))
    assert p.get_active("BANKNIFTY") is not None
    p.reset()
    assert p.get_active("BANKNIFTY") is None


def test_multiple_symbols():
    p = CandlePipeline()
    p.process(_make_tick(symbol="BANKNIFTY", price=45000.0, ts=0))
    p.process(_make_tick(symbol="NIFTY", price=22000.0, ts=0))
    bn = p.get_active("BANKNIFTY")
    n = p.get_active("NIFTY")
    assert bn is not None and bn.open == 45000.0
    assert n is not None and n.open == 22000.0