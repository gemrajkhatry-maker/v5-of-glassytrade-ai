#!/usr/bin/env python3
"""
Live test: all real-time market feeds for TCS on NSE.

Tests in order:
  1. REST snapshot  — get_quote (LTP, OHLC, depth)
  2. Ticker stream  — stream_ticker (LTP-only WS feed)
  3. Quote stream   — stream_quotes (full quote WS feed)
  4. Depth-5 stream — stream_depth(depth_level=5) via FEED_TYPE_FULL
  5. Depth-20 stream — stream_depth_20 via dedicated depth WS
  6. Depth-200 stream — stream_depth_200 via full-depth WS

Run: .venv/bin/python brokers/scripts/test_tcs_all_feeds_live.py
"""
import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.entities import Instrument, Quote, Tick, MarketDepth
from brokers.broker.types import Exchange

SYMBOL = "TCS"
EXCHANGE = Exchange.NSE
TICK_LIMIT = 3       # ticks to collect before moving on
DEPTH_LIMIT = 2      # depth packets per side (bid + ask = 4 packets)
TIMEOUT = 30         # seconds per stream test

PASSED = 0
FAILED = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    mark = "PASS" if cond else "FAIL"
    if cond:
        PASSED += 1
    else:
        FAILED += 1
    suffix = f" ({detail})" if detail else ""
    print(f"  {mark}: {name}{suffix}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# REST Snapshot
# ---------------------------------------------------------------------------

async def test_rest_snapshot(broker: DhanBroker) -> None:
    section(f"[1/6] REST snapshot — get_quote({SYMBOL})")
    inst = Instrument(symbol=SYMBOL, exchange=EXCHANGE)
    q = broker.get_quote(inst)

    ok("Quote returned", isinstance(q, Quote))
    ok("LTP > 0", q.ltp > 0, f"ltp={q.ltp}")
    ok("Open >= 0", q.open >= 0, f"open={q.open}")
    ok("High >= 0", q.high >= 0, f"high={q.high}")
    ok("Low >= 0", q.low >= 0, f"low={q.low}")
    ok("Close >= 0", q.close >= 0, f"close={q.close}")
    ok("Volume >= 0", q.volume >= 0, f"volume={q.volume}")
    ok("Bid >= 0", q.bid >= 0, f"bid={q.bid}")
    ok("Ask >= 0", q.ask >= 0, f"ask={q.ask}")
    ok("has_depth", q.has_depth,
       f"bid_depth={'yes' if q.bid_depth else 'no'} ask_depth={'yes' if q.ask_depth else 'no'}")
    if q.bid_depth:
        lvl = q.bid_depth[0]
        ok("bid_depth[0] price", lvl.price > 0, f"price={lvl.price}")
        ok("bid_depth[0] qty", lvl.quantity >= 0, f"qty={lvl.quantity}")
    if q.ask_depth:
        lvl = q.ask_depth[0]
        ok("ask_depth[0] price", lvl.price > 0, f"price={lvl.price}")
        ok("ask_depth[0] qty", lvl.quantity >= 0, f"qty={lvl.quantity}")
    print(f"\n  Snapshot: LTP={q.ltp}  OHLC={q.open}/{q.high}/{q.low}/{q.close}  vol={q.volume}")


# ---------------------------------------------------------------------------
# Ticker stream (LTP only)
# ---------------------------------------------------------------------------

async def test_ticker_stream(broker: DhanBroker) -> None:
    section(f"[2/6] Ticker stream — stream_ticker({SYMBOL})")
    inst = Instrument(symbol=SYMBOL, exchange=EXCHANGE)
    ticks = []

    async def collect():
        async for tick in broker.stream_ticker([inst]):
            ticks.append(tick)
            print(f"  tick #{len(ticks)}: ltp={tick.price}  vol={tick.volume}  ts={tick.timestamp}")
            if len(ticks) >= TICK_LIMIT:
                break

    try:
        await asyncio.wait_for(collect(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"  [timeout after {TIMEOUT}s — got {len(ticks)} ticks]")

    ok("Received ticks", len(ticks) > 0, f"count={len(ticks)}")
    if ticks:
        t = ticks[0]
        ok("Tick is Tick type", isinstance(t, Tick))
        ok("Tick instrument matches", t.instrument.symbol == SYMBOL, f"symbol={t.instrument.symbol}")
        ok("Tick price > 0", t.price > 0, f"price={t.price}")
        ok("Tick timestamp", isinstance(t.timestamp, datetime))


# ---------------------------------------------------------------------------
# Quote stream (LTP + OHLC + volume)
# ---------------------------------------------------------------------------

async def test_quote_stream(broker: DhanBroker) -> None:
    section(f"[3/6] Quote stream — stream_quotes({SYMBOL})")
    inst = Instrument(symbol=SYMBOL, exchange=EXCHANGE)
    quotes = []

    async def collect():
        async for q in broker.stream_quotes([inst]):
            quotes.append(q)
            print(f"  quote #{len(quotes)}: ltp={q.ltp}  o={q.open} h={q.high} l={q.low}  vol={q.volume}")
            if len(quotes) >= TICK_LIMIT:
                break

    try:
        await asyncio.wait_for(collect(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"  [timeout after {TIMEOUT}s — got {len(quotes)} quotes]")

    ok("Received quotes", len(quotes) > 0, f"count={len(quotes)}")
    if quotes:
        q = quotes[0]
        ok("Quote is Quote type", isinstance(q, Quote))
        ok("Quote instrument", q.instrument.symbol == SYMBOL, f"symbol={q.instrument.symbol}")
        ok("Quote LTP > 0", q.ltp > 0, f"ltp={q.ltp}")
        ok("Quote open >= 0", q.open >= 0, f"open={q.open}")
        ok("Quote volume >= 0", q.volume >= 0, f"vol={q.volume}")


# ---------------------------------------------------------------------------
# Depth-5 stream (regular feed, FEED_TYPE_FULL)
# ---------------------------------------------------------------------------

async def test_depth5_stream(broker: DhanBroker) -> None:
    section(f"[4/6] Depth-5 stream — stream_depth({SYMBOL}, depth_level=5)")
    inst = Instrument(symbol=SYMBOL, exchange=EXCHANGE)
    packets = []

    async def collect():
        async for md in broker.stream_depth([inst], depth_level=5):
            packets.append(md)
            print(f"  depth5 #{len(packets)}: symbol={md.symbol}  side={md.side}  levels={len(md.levels)}"
                  f"  best={md.levels[0].price if md.levels else 'n/a'}")
            if len(packets) >= DEPTH_LIMIT * 2:
                break

    try:
        await asyncio.wait_for(collect(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"  [timeout after {TIMEOUT}s — got {len(packets)} packets]")

    ok("Received depth5 packets", len(packets) > 0, f"count={len(packets)}")
    if packets:
        md = packets[0]
        ok("MarketDepth type", isinstance(md, MarketDepth))
        ok("Symbol backfilled", md.symbol == SYMBOL, f"symbol={md.symbol}")
        ok("Side is bid or ask", md.side in ("bid", "ask"), f"side={md.side}")
        ok("Has levels", len(md.levels) > 0, f"levels={len(md.levels)}")
        if md.levels:
            ok("Level price > 0", md.levels[0].price > 0, f"price={md.levels[0].price}")
            ok("Level qty >= 0", md.levels[0].quantity >= 0, f"qty={md.levels[0].quantity}")


# ---------------------------------------------------------------------------
# Depth-20 stream (dedicated depth WS)
# ---------------------------------------------------------------------------

async def test_depth20_stream(broker: DhanBroker) -> None:
    section(f"[5/6] Depth-20 stream — stream_depth_20({SYMBOL})")
    inst = Instrument(symbol=SYMBOL, exchange=EXCHANGE)
    packets = []

    async def collect():
        async for md in broker.stream_depth_20([inst]):
            packets.append(md)
            print(f"  depth20 #{len(packets)}: symbol={md.symbol}  side={md.side}  levels={len(md.levels)}"
                  f"  best={md.levels[0].price if md.levels else 'n/a'}")
            if len(packets) >= DEPTH_LIMIT * 2:
                break

    try:
        await asyncio.wait_for(collect(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"  [timeout after {TIMEOUT}s — got {len(packets)} packets]")

    ok("Received depth20 packets", len(packets) > 0, f"count={len(packets)}")
    if packets:
        md = packets[0]
        ok("MarketDepth type", isinstance(md, MarketDepth))
        ok("Symbol backfilled", md.symbol == SYMBOL, f"symbol={md.symbol}")
        ok("Side is bid or ask", md.side in ("bid", "ask"), f"side={md.side}")
        ok("Has >=1 level", len(md.levels) >= 1, f"levels={len(md.levels)}")
        ok("Has >=10 levels (20-lvl feed)", len(md.levels) >= 10, f"levels={len(md.levels)}")
        if md.levels:
            ok("Level price > 0", md.levels[0].price > 0, f"price={md.levels[0].price}")
            ok("Level qty >= 0", md.levels[0].quantity >= 0, f"qty={md.levels[0].quantity}")


# ---------------------------------------------------------------------------
# Depth-200 stream (full-depth WS)
# ---------------------------------------------------------------------------

async def test_depth200_stream(broker: DhanBroker) -> None:
    section(f"[6/6] Depth-200 stream — stream_depth_200({SYMBOL})")
    inst = Instrument(symbol=SYMBOL, exchange=EXCHANGE)
    packets = []

    async def collect():
        async for md in broker.stream_depth_200([inst]):
            packets.append(md)
            print(f"  depth200 #{len(packets)}: symbol={md.symbol}  side={md.side}  levels={len(md.levels)}"
                  f"  best={md.levels[0].price if md.levels else 'n/a'}")
            if len(packets) >= DEPTH_LIMIT * 2:
                break

    try:
        await asyncio.wait_for(collect(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        print(f"  [timeout after {TIMEOUT}s — got {len(packets)} packets]")

    ok("Received depth200 packets", len(packets) > 0, f"count={len(packets)}")
    if packets:
        md = packets[0]
        ok("MarketDepth type", isinstance(md, MarketDepth))
        ok("Symbol backfilled", md.symbol == SYMBOL, f"symbol={md.symbol}")
        ok("Side is bid or ask", md.side in ("bid", "ask"), f"side={md.side}")
        ok("Has >=1 level", len(md.levels) >= 1, f"levels={len(md.levels)}")
        if md.levels:
            ok("Level price > 0", md.levels[0].price > 0, f"price={md.levels[0].price}")
            ok("Level qty >= 0", md.levels[0].quantity >= 0, f"qty={md.levels[0].quantity}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    if not os.getenv("DHAN_CLIENT_ID") or not os.getenv("DHAN_ACCESS_TOKEN"):
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    print(f"\nTesting all feeds for {SYMBOL} on {EXCHANGE.value}")
    print(f"Collecting {TICK_LIMIT} ticks / {DEPTH_LIMIT*2} depth packets per stream (timeout={TIMEOUT}s)")

    broker = DhanBroker.create()
    await broker.initialize()

    try:
        await test_rest_snapshot(broker)
        await asyncio.sleep(1)
        await test_ticker_stream(broker)
        await asyncio.sleep(1)
        await test_quote_stream(broker)
        await asyncio.sleep(1)
        await test_depth5_stream(broker)
        await asyncio.sleep(1)
        await test_depth20_stream(broker)
        await asyncio.sleep(1)
        await test_depth200_stream(broker)
    finally:
        await broker.close()

    print(f"\n{'=' * 60}")
    if FAILED == 0:
        print(f"ALL {PASSED} CHECKS PASSED — {SYMBOL} all feeds OK")
    else:
        print(f"RESULTS: {PASSED} passed, {FAILED} FAILED")
    print(f"{'=' * 60}\n")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())
