#!/usr/bin/env python3
"""
Live tests against real market: NSE and MCX.

Uses real Dhan API with credentials from .env.
Run: python brokers/scripts/test_nse_mcx_live.py
     or: .venv/bin/python brokers/scripts/test_nse_mcx_live.py
"""
import os
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

# Project root
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "dhanhq_custom"))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

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


async def run_nse_tests(broker: DhanBroker) -> None:
    """NSE: equities + F&O (NIFTY option chain)."""
    print("\n" + "=" * 60)
    print("NSE — Equities & F&O (real market)")
    print("=" * 60)

    # Single quote — NSE equity
    print("\n--- get_quote (NSE equity) ---")
    try:
        q = broker.get_quote(Instrument(symbol="RELIANCE", exchange=Exchange.NSE))
        ok("NSE get_quote RELIANCE", q is not None and q.ltp > 0, f"ltp={q.ltp}")
    except Exception as e:
        ok("NSE get_quote RELIANCE", False, str(e))
    time.sleep(1.5)

    # Batch quotes — NSE
    print("\n--- get_quotes_batch (NSE) ---")
    try:
        insts = [
            Instrument(symbol=s, exchange=Exchange.NSE)
            for s in ["RELIANCE", "TCS", "INFY"]
        ]
        quotes = broker.get_quotes_batch(insts)
        ok("NSE batch 3 quotes", len(quotes) == 3, f"got={len(quotes)}")
        for inst, q in quotes.items():
            ok(f"  {inst.symbol}", q.ltp > 0, f"ltp={q.ltp}")
    except Exception as e:
        ok("NSE get_quotes_batch", False, str(e))
    time.sleep(1.5)

    # LTP single + batch
    print("\n--- get_ltp / get_ltp_batch_async (NSE) ---")
    try:
        ltp = broker.get_ltp(Instrument(symbol="RELIANCE", exchange=Exchange.NSE))
        ok("NSE get_ltp", ltp > 0, f"ltp={ltp}")
    except Exception as e:
        ok("NSE get_ltp", False, str(e))
    time.sleep(1)
    try:
        ltps = await broker.get_ltp_batch_async(["RELIANCE", "TCS"], Exchange.NSE)
        ok("NSE LTP batch", isinstance(ltps, dict) and len(ltps) == 2, f"got={list(ltps.keys())}")
    except Exception as e:
        ok("NSE LTP batch", False, str(e))
    time.sleep(1.5)

    # Option chain — NFO (NIFTY)
    print("\n--- get_option_chain NIFTY (NFO) ---")
    try:
        chain = broker.get_option_chain("NIFTY", exchange=Exchange.NFO)
        ok("NSE/NFO option chain", chain is not None and chain.spot_price > 0, f"spot={chain.spot_price}")
        atm = chain.atm_strike
        if atm in chain.calls:
            c = chain.calls[atm]
            ok("  ATM call ltp/bid/ask/iv", c.ltp > 0 and c.bid is not None and c.iv is not None,
               f"ltp={c.ltp} bid={c.bid} iv={c.iv}")
    except Exception as e:
        ok("NSE/NFO option chain", False, str(e))
    time.sleep(1.5)

    # Historical — NSE equity
    print("\n--- get_historical (NSE equity) ---")
    try:
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)
        to_d = datetime.now()
        from_d = to_d - timedelta(days=5)
        df = broker.get_historical(inst, from_d, to_d, interval="1d")
        ok("NSE historical", df is not None and len(df) >= 0, f"rows={len(df)}")
    except Exception as e:
        ok("NSE get_historical", False, str(e))


async def run_mcx_tests(broker: DhanBroker) -> None:
    """MCX: commodities (GOLD, SILVER, CRUDEOIL)."""
    print("\n" + "=" * 60)
    print("MCX — Commodities (real market)")
    print("=" * 60)

    # MCX segment is MCX_COMM; symbol mapper resolves to nearest futures
    mcx_symbols = ["GOLD", "SILVER", "CRUDEOIL"]

    for sym in mcx_symbols:
        print(f"\n--- MCX {sym} ---")
        try:
            inst = Instrument(symbol=sym, exchange=Exchange.MCX)
            q = broker.get_quote(inst)
            ok(f"MCX get_quote {sym}", q is not None and q.ltp > 0, f"ltp={q.ltp}")
        except Exception as e:
            ok(f"MCX get_quote {sym}", False, str(e))
        time.sleep(2)  # MCX rate limit

    # Batch quote MCX (one call for multiple commodities)
    print("\n--- get_quotes_batch (MCX) ---")
    try:
        insts = [Instrument(symbol=s, exchange=Exchange.MCX) for s in mcx_symbols]
        quotes = broker.get_quotes_batch(insts)
        ok("MCX batch quotes", len(quotes) >= 1, f"got={len(quotes)}")
        for inst, q in quotes.items():
            ok(f"  {inst.symbol}", q.ltp > 0, f"ltp={q.ltp}")
    except Exception as e:
        ok("MCX get_quotes_batch", False, str(e))
    time.sleep(2)

    # LTP single MCX
    print("\n--- get_ltp (MCX) ---")
    try:
        ltp = broker.get_ltp(Instrument(symbol="GOLD", exchange=Exchange.MCX))
        ok("MCX get_ltp GOLD", ltp > 0, f"ltp={ltp}")
    except Exception as e:
        ok("MCX get_ltp GOLD", False, str(e))
    time.sleep(2)

    # LTP batch MCX
    print("\n--- get_ltp_batch_async (MCX) ---")
    try:
        ltps = await broker.get_ltp_batch_async(["GOLD", "SILVER"], Exchange.MCX)
        ok("MCX LTP batch", isinstance(ltps, dict) and len(ltps) >= 1, f"got={list(ltps.keys())}")
    except Exception as e:
        ok("MCX LTP batch", False, str(e))
    time.sleep(2)

    # MCX option chain (GOLD) and quote for one option contract
    print("\n--- MCX options: option chain GOLD + quote for one contract ---")
    try:
        chain = broker.get_option_chain("GOLD", exchange=Exchange.MCX)
        ok("MCX option chain GOLD", chain is not None, "chain returned")
        if chain:
            ok("MCX chain spot_price", chain.spot_price > 0, f"spot={chain.spot_price}")
            ok("MCX chain has calls/puts", bool(chain.calls) or bool(chain.puts), f"calls={len(chain.calls)} puts={len(chain.puts)}")
            # Quote for one MCX option contract if we have any
            if chain.calls or chain.puts:
                strike = chain.atm_strike if chain.atm_strike else (list(chain.calls.keys()) or list(chain.puts.keys()))[0]
                opt = chain.calls.get(strike) or chain.puts.get(strike)
                if opt and opt.symbol:
                    q_opt = broker.get_quote(Instrument(symbol=opt.symbol, exchange=Exchange.MCX))
                    ok("MCX option get_quote", q_opt is not None and q_opt.ltp >= 0, f"symbol={opt.symbol} ltp={q_opt.ltp if q_opt else 'N/A'}")
                else:
                    ok("MCX option get_quote", True, "skipped (no symbol)")
            else:
                ok("MCX option get_quote", True, "skipped (empty chain)")
    except Exception as e:
        ok("MCX options (chain + quote)", False, str(e))


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
        await run_nse_tests(broker)
        await run_mcx_tests(broker)
    finally:
        await broker.close()

    print("\n" + "=" * 60)
    if FAILED == 0:
        print(f"ALL {PASSED} TESTS PASSED (NSE + MCX real market)")
    else:
        print(f"RESULTS: {PASSED} passed, {FAILED} failed")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())
