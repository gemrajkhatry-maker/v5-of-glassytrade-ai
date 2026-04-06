"""Unit tests for CandleBuilderProcessor.

Coverage:
  - test_candle_builds_from_ticks       — multiple ticks in same window aggregate correctly
  - test_candle_closes_on_new_period    — new period tick closes previous candle (closed=True)
  - test_live_update_emitted_per_tick   — closed=False emitted for every tick
  - test_interval_1m                   — 1m interval flooring
  - test_interval_5m                   — 5m interval flooring
  - test_multi_symbol                  — separate candle state per symbol
  - test_delta_calculation             — delta = buy_qty - sell_qty
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone, timedelta

from app.pipeline.channel import Channel
from app.pipeline.message import Message, RawTickPayload, CandlePayload
from app.pipeline.processor import ProcessorConfig
from app.pipeline.processors.candle import CandleBuilderProcessor, _parse_interval_minutes


IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(
    symbol: str,
    ltp: float,
    ts: datetime,
    volume: int = 0,
    total_buy_qty: int = 0,
    total_sell_qty: int = 0,
) -> Message:
    """Convenience factory for RawTickMessage."""
    return Message(
        payload=RawTickPayload(
            ltp=ltp,
            volume=volume,
            total_buy_qty=total_buy_qty,
            total_sell_qty=total_sell_qty,
            source="test",
        ),
        symbol=symbol,
        timestamp=ts,
        source_processor="test_source",
        pipeline_id="test",
    )


async def _run_processor(
    ticks: list[Message],
    interval: str = "5m",
) -> list[Message]:
    """Feed *ticks* through a CandleBuilderProcessor and return all candle messages."""
    processor = CandleBuilderProcessor()
    config = ProcessorConfig(
        name="candle_builder_test",
        processor_class="app.pipeline.processors.candle.CandleBuilderProcessor",
        inbox={"raw_ticks": "raw_ticks"},
        outbox={"candles": "candles"},
        settings={"interval": interval},
    )
    await processor.setup(config)

    in_ch: Channel = Channel("raw_ticks", capacity=200)
    out_ch: Channel = Channel("candles", capacity=200)

    # Feed all ticks then close the channel so the processor loop terminates
    for t in ticks:
        await in_ch.send(t)
    await in_ch.close()

    await processor.process({"raw_ticks": in_ch}, {"candles": out_ch})

    results: list[Message] = []
    while True:
        try:
            msg = out_ch._queue.get_nowait()
            if msg is None:
                break
            results.append(msg)
        except Exception:
            break
    return results


# ---------------------------------------------------------------------------
# Tests — interval parsing (pure-unit, no async)
# ---------------------------------------------------------------------------

def test_parse_interval_1m():
    assert _parse_interval_minutes("1m") == 1


def test_parse_interval_5m():
    assert _parse_interval_minutes("5m") == 5


def test_parse_interval_15m():
    assert _parse_interval_minutes("15m") == 15


def test_parse_interval_1h():
    assert _parse_interval_minutes("1h") == 60


# ---------------------------------------------------------------------------
# Tests — candle aggregation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_candle_builds_from_ticks():
    """Three ticks in the same 5m window must produce one running candle state.

    OHLC expectations:
      open  = ltp of first tick
      high  = max(ltp) across ticks
      low   = min(ltp) across ticks
      close = ltp of last tick
    """
    base = datetime(2026, 3, 14, 9, 16, 0, tzinfo=IST)   # inside 09:15 window

    ticks = [
        _make_tick("NIFTY", 100.0, base.replace(second=0), volume=100, total_buy_qty=60, total_sell_qty=40),
        _make_tick("NIFTY", 102.0, base.replace(second=30), volume=150, total_buy_qty=90, total_sell_qty=60),
        _make_tick("NIFTY", 98.0,  base.replace(second=59), volume=200, total_buy_qty=110, total_sell_qty=90),
    ]

    results = await _run_processor(ticks, interval="5m")

    # Three ticks => three live-candle messages, all closed=False
    assert len(results) == 3, f"Expected 3 messages, got {len(results)}"
    assert all(isinstance(m.payload, CandlePayload) for m in results)
    assert all(not m.payload.closed for m in results), "All messages within same period should be closed=False"

    last = results[-1].payload
    assert last.open == 100.0
    assert last.high == 102.0
    assert last.low == 98.0
    assert last.close == 98.0


@pytest.mark.asyncio
async def test_candle_closes_on_new_period():
    """When a tick arrives in a new candle period, the previous candle is emitted
    with closed=True before the new live candle (closed=False) is emitted."""
    t1 = datetime(2026, 3, 14, 9, 16, 0, tzinfo=IST)   # inside 09:15–09:20 window
    t2 = datetime(2026, 3, 14, 9, 21, 0, tzinfo=IST)   # inside 09:20–09:25 window (new period)

    ticks = [
        _make_tick("BNF", 200.0, t1, volume=500, total_buy_qty=300, total_sell_qty=200),
        _make_tick("BNF", 205.0, t2, volume=600, total_buy_qty=350, total_sell_qty=250),
    ]

    results = await _run_processor(ticks, interval="5m")

    # Tick 1 -> 1 live message; Tick 2 -> 1 closed (prev) + 1 live (new) = 3 total
    assert len(results) == 3, f"Expected 3 messages, got {len(results)}"

    # First message: live candle for period 1
    assert results[0].payload.closed is False
    assert results[0].payload.close == 200.0

    # Second message: closed candle for period 1
    assert results[1].payload.closed is True
    assert results[1].payload.close == 200.0
    assert results[1].symbol == "BNF"

    # Third message: live candle for period 2
    assert results[2].payload.closed is False
    assert results[2].payload.open == 205.0


@pytest.mark.asyncio
async def test_live_update_emitted_per_tick():
    """A closed=False message must be emitted for every incoming tick."""
    base = datetime(2026, 3, 14, 9, 15, 0, tzinfo=IST)
    n = 10
    ticks = [
        _make_tick("SYM", 100.0 + i, base.replace(second=i * 5), volume=100 + i * 10)
        for i in range(n)
    ]

    results = await _run_processor(ticks, interval="5m")

    # All ticks land in the same 5m window (0–50 seconds into 09:15)
    assert len(results) == n, f"Expected {n} live messages, got {len(results)}"
    assert all(not m.payload.closed for m in results)


@pytest.mark.asyncio
async def test_interval_1m():
    """Ticks 60+ seconds apart should trigger separate 1m candles."""
    t1 = datetime(2026, 3, 14, 9, 15, 10, tzinfo=IST)   # 09:15 candle
    t2 = datetime(2026, 3, 14, 9, 16, 5, tzinfo=IST)    # 09:16 candle

    ticks = [
        _make_tick("X", 50.0, t1),
        _make_tick("X", 55.0, t2),
    ]

    results = await _run_processor(ticks, interval="1m")

    # t1 -> 1 live; t2 -> 1 closed + 1 live = 3
    assert len(results) == 3
    assert results[1].payload.closed is True
    assert results[2].payload.closed is False
    assert results[2].payload.open == 55.0


@pytest.mark.asyncio
async def test_interval_5m():
    """Ticks within the same 5m bucket must share a candle; ticks 5m apart must not."""
    t1 = datetime(2026, 3, 14, 9, 17, 0, tzinfo=IST)   # 09:15 bucket
    t2 = datetime(2026, 3, 14, 9, 19, 0, tzinfo=IST)   # still 09:15 bucket
    t3 = datetime(2026, 3, 14, 9, 21, 0, tzinfo=IST)   # 09:20 bucket (new period)

    ticks = [
        _make_tick("Y", 10.0, t1),
        _make_tick("Y", 11.0, t2),
        _make_tick("Y", 12.0, t3),
    ]

    results = await _run_processor(ticks, interval="5m")

    # t1 -> live; t2 -> live (same period); t3 -> closed(prev) + live(new) = 4
    assert len(results) == 4

    # First two are live updates in same candle
    assert results[0].payload.closed is False
    assert results[1].payload.closed is False

    # Third is the closed candle from the first period
    assert results[2].payload.closed is True
    assert results[2].payload.open == 10.0
    assert results[2].payload.close == 11.0

    # Fourth is the live candle for the new period
    assert results[3].payload.closed is False
    assert results[3].payload.open == 12.0


@pytest.mark.asyncio
async def test_multi_symbol():
    """Each symbol must maintain an independent candle state."""
    ts = datetime(2026, 3, 14, 9, 15, 0, tzinfo=IST)

    ticks = [
        _make_tick("NIFTY",    200.0, ts),
        _make_tick("BANKNIFTY", 400.0, ts),
        _make_tick("NIFTY",    205.0, ts.replace(second=30)),
        _make_tick("BANKNIFTY", 410.0, ts.replace(second=45)),
    ]

    results = await _run_processor(ticks, interval="5m")

    # 4 ticks -> 4 live messages (all in same period per symbol)
    assert len(results) == 4

    nifty_msgs = [m for m in results if m.symbol == "NIFTY"]
    bnf_msgs   = [m for m in results if m.symbol == "BANKNIFTY"]

    assert len(nifty_msgs) == 2
    assert len(bnf_msgs) == 2

    # NIFTY open should be 200, close should be 205
    assert nifty_msgs[0].payload.open == 200.0
    assert nifty_msgs[-1].payload.close == 205.0

    # BANKNIFTY open should be 400, close should be 410
    assert bnf_msgs[0].payload.open == 400.0
    assert bnf_msgs[-1].payload.close == 410.0


@pytest.mark.asyncio
async def test_delta_calculation():
    """delta must equal total_buy_qty - total_sell_qty (per-tick increments).

    The processor treats total_buy_qty / total_sell_qty as cumulative session
    counters (same as the TradingEngine).  The very first tick for a symbol
    establishes a baseline — it produces zero per-tick buy/sell — and subsequent
    ticks contribute the incremental difference.

    Tick 1 (baseline): cumulative buy=100, sell=60  -> per-tick buy=0, sell=0
                       candle delta=0 (no prior baseline yet)
    Tick 2:            cumulative buy=160, sell=90  -> per-tick buy=60, sell=30
                       candle delta = 60 - 30 = 30
    Tick 3:            cumulative buy=220, sell=120 -> per-tick buy=60, sell=30
                       candle delta = (60+60) - (30+30) = 60
    """
    ts = datetime(2026, 3, 14, 9, 15, 0, tzinfo=IST)

    ticks = [
        _make_tick("D", 100.0, ts,                    total_buy_qty=100, total_sell_qty=60),
        _make_tick("D", 101.0, ts.replace(second=30), total_buy_qty=160, total_sell_qty=90),
        _make_tick("D", 102.0, ts.replace(second=45), total_buy_qty=220, total_sell_qty=120),
    ]

    results = await _run_processor(ticks, interval="5m")

    assert len(results) == 3

    # Tick 1: baseline — cumulative buy/sell delta is 0 (body-ratio fallback,
    # but price is at open so spread=0 => delta=0)
    assert results[0].payload.delta == pytest.approx(0.0)

    # Tick 2: per-tick buy=60, sell=30 -> candle delta=30
    assert results[1].payload.delta == pytest.approx(30.0)

    # Tick 3: per-tick buy=60, sell=30 added -> candle total buy=120, sell=60 -> delta=60
    assert results[2].payload.delta == pytest.approx(60.0)
