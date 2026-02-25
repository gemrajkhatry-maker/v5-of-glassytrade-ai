#!/usr/bin/env python3
"""
Live test: full quote data (OHLC, volume, OI) and market depth from Dhan API.

Uses POST /v2/marketfeed/quote which returns last_price, ohlc, depth (buy/sell
levels), volume, oi. Verifies that Quote has all fields and depth levels.

Run: .venv/bin/python brokers/scripts/test_full_quote_and_depth_live.py
"""
import os
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "dhanhq_custom"))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.entities import Instrument, DepthLevel, Quote
from brokers.broker.types import Exchange

PASSED = 0
FAILED = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS: {name}" + (f" ({detail})" if detail else ""))
    else:
        FAILED += 1
        print(f"  FAIL: {name}" + (f" ({detail})" if detail else ""))


async def main() -> None:
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    if not os.getenv("DHAN_CLIENT_ID") or not os.getenv("DHAN_ACCESS_TOKEN"):
        print("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    broker = DhanBroker.create()
    await broker.initialize()

    try:
        # ---------------------------------------------------------------------
        # NSE — Full quote (single)
        # ---------------------------------------------------------------------
        print("=" * 60)
        print("NSE — Full quote (get_quote)")
        print("=" * 60)

        inst_nse = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)
        q = broker.get_quote(inst_nse)

        ok("Quote returned", isinstance(q, Quote))
        ok("LTP > 0", q.ltp > 0, f"ltp={q.ltp}")
        ok("OHLC: open", q.open >= 0, f"open={q.open}")
        ok("OHLC: high", q.high >= 0, f"high={q.high}")
        ok("OHLC: low", q.low >= 0, f"low={q.low}")
        ok("OHLC: close", q.close >= 0, f"close={q.close}")
        ok("Volume >= 0", q.volume >= 0, f"volume={q.volume}")
        ok("Best bid", q.bid >= 0, f"bid={q.bid}")
        ok("Best ask", q.ask >= 0, f"ask={q.ask}")
        ok("Spread", q.spread is None or q.spread >= 0, f"spread={q.spread}")

        # Market depth (from /marketfeed/quote depth.buy / depth.sell)
        ok("has_depth", q.has_depth, f"bid_depth={q.bid_depth is not None} ask_depth={q.ask_depth is not None}")
        if q.bid_depth:
            ok("bid_depth levels", len(q.bid_depth) >= 1, f"levels={len(q.bid_depth)}")
            for i, lev in enumerate(q.bid_depth[:3]):
                ok(f"  bid_level[{i}]", isinstance(lev, DepthLevel) and lev.price >= 0 and lev.quantity >= 0,
                   f"price={lev.price} qty={lev.quantity}")
        if q.ask_depth:
            ok("ask_depth levels", len(q.ask_depth) >= 1, f"levels={len(q.ask_depth)}")
            for i, lev in enumerate(q.ask_depth[:3]):
                ok(f"  ask_level[{i}]", isinstance(lev, DepthLevel) and lev.price >= 0 and lev.quantity >= 0,
                   f"price={lev.price} qty={lev.quantity}")

        time.sleep(1.5)

        # ---------------------------------------------------------------------
        # NSE — Batch quotes with full data + depth
        # ---------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("NSE — Batch quotes (full data + depth)")
        print("=" * 60)

        instruments = [
            Instrument(symbol=s, exchange=Exchange.NSE)
            for s in ["RELIANCE", "TCS"]
        ]
        quotes = await broker._get_quotes_batch_async(instruments)
        ok("Batch size", len(quotes) == 2, f"got={len(quotes)}")

        for inst, q in quotes.items():
            ok(f"{inst.symbol} LTP", q.ltp > 0, f"ltp={q.ltp}")
            ok(f"{inst.symbol} OHLC", q.open >= 0 and q.high >= 0, f"o={q.open} h={q.high}")
            ok(f"{inst.symbol} volume", q.volume >= 0, f"vol={q.volume}")
            ok(f"{inst.symbol} has_depth", q.has_depth, "")
            if q.bid_depth:
                ok(f"{inst.symbol} bid_depth len", len(q.bid_depth) >= 1, f"n={len(q.bid_depth)}")
            if q.ask_depth:
                ok(f"{inst.symbol} ask_depth len", len(q.ask_depth) >= 1, f"n={len(q.ask_depth)}")

        time.sleep(1.5)

        # ---------------------------------------------------------------------
        # NFO — Option quote (full + depth, OI)
        # ---------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("NFO — Option quote (OI + depth)")
        print("=" * 60)

        # Get option chain to resolve ATM symbol
        chain = await broker.get_option_chain_async("NIFTY", Exchange.NFO, 0)
        atm = chain.atm_strike
        if atm in chain.calls:
            opt_symbol = chain.calls[atm].symbol  # e.g. "NIFTY 17 FEB 25700 CALL"
            inst_opt = Instrument(symbol=opt_symbol, exchange=Exchange.NFO)
            q_opt = broker.get_quote(inst_opt)
            ok("Option quote", q_opt is not None and q_opt.ltp > 0, f"ltp={q_opt.ltp}")
            ok("Option OI", q_opt.oi is None or q_opt.oi >= 0, f"oi={q_opt.oi}")
            ok("Option has_depth", q_opt.has_depth, "")
        else:
            ok("Option quote", False, "no ATM call")

        time.sleep(1.5)

        # ---------------------------------------------------------------------
        # MCX — Full quote + depth
        # ---------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("MCX — Full quote + depth")
        print("=" * 60)

        inst_mcx = Instrument(symbol="GOLD", exchange=Exchange.MCX)
        q_mcx = broker.get_quote(inst_mcx)
        ok("MCX quote", q_mcx is not None and q_mcx.ltp > 0, f"ltp={q_mcx.ltp}")
        ok("MCX OHLC", q_mcx.open >= 0 and q_mcx.high >= 0, f"o={q_mcx.open} h={q_mcx.high}")
        ok("MCX has_depth", q_mcx.has_depth, "")
        if q_mcx.bid_depth:
            ok("MCX bid_depth", len(q_mcx.bid_depth) >= 1, f"levels={len(q_mcx.bid_depth)}")
        if q_mcx.ask_depth:
            ok("MCX ask_depth", len(q_mcx.ask_depth) >= 1, f"levels={len(q_mcx.ask_depth)}")

    finally:
        await broker.close()

    print("\n" + "=" * 60)
    if FAILED == 0:
        print(f"ALL {PASSED} TESTS PASSED (full quote + market depth)")
    else:
        print(f"RESULTS: {PASSED} passed, {FAILED} failed")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())
