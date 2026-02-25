#!/usr/bin/env python3
"""
Verify end-to-end: historical data, option chains, expiries for NSE and MCX.

Run with PaperBroker (no credentials):
  python brokers/scripts/verify_e2e_nse_mcx.py

Run with real Dhan (requires DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN in env):
  python brokers/scripts/verify_e2e_nse_mcx.py --live

Exits 0 if all checks pass, 1 otherwise.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Project root for imports
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load .env so DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN are available for --live
try:
    from dotenv import load_dotenv
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
except ImportError:
    pass


def run_paper_checks():
    """Use BrokerGateway.paper() - no API."""
    from brokers.gateway import BrokerGateway
    from brokers.broker.types import Exchange

    gateway = BrokerGateway.paper()
    to_date = datetime.now()
    from_date = to_date - timedelta(days=5)
    errors = []

    # NSE
    try:
        q = gateway.get_quote("RELIANCE", Exchange.NSE)
        assert q and q.ltp > 0, "NSE quote"
    except Exception as e:
        errors.append(f"NSE quote: {e}")
    try:
        df = gateway.get_historical("RELIANCE", Exchange.NSE, from_date, to_date, "1d")
        assert df is not None and len(df) >= 1, "NSE historical"
    except Exception as e:
        errors.append(f"NSE historical: {e}")
    try:
        chain = gateway.get_option_chain("NIFTY", Exchange.NFO)
        assert chain and chain.underlying.symbol == "NIFTY", "NFO option chain"
    except Exception as e:
        errors.append(f"NFO option chain: {e}")
    try:
        exp = gateway.get_expiries("NIFTY", Exchange.NFO)
        assert exp and len(exp) >= 1, "NFO expiries"
    except Exception as e:
        errors.append(f"NFO expiries: {e}")

    # MCX
    try:
        q = gateway.get_quote("GOLD", Exchange.MCX)
        assert q and q.ltp > 0, "MCX quote"
    except Exception as e:
        errors.append(f"MCX quote: {e}")
    try:
        df = gateway.get_historical("GOLD", Exchange.MCX, from_date, to_date, "1d")
        assert df is not None and len(df) >= 1, "MCX historical"
    except Exception as e:
        errors.append(f"MCX historical: {e}")
    try:
        chain = gateway.get_option_chain("GOLD", Exchange.MCX)
        assert chain and chain.underlying.exchange == Exchange.MCX, "MCX option chain"
    except Exception as e:
        errors.append(f"MCX option chain: {e}")
    try:
        exp = gateway.get_expiries("GOLD", Exchange.MCX)
        assert exp and len(exp) >= 1, "MCX expiries"
    except Exception as e:
        errors.append(f"MCX expiries: {e}")

    return errors


def run_live_checks():
    """Use BrokerGateway.dhan() - requires env credentials. Runs in a single event loop."""
    if not os.environ.get("DHAN_CLIENT_ID") or not os.environ.get("DHAN_ACCESS_TOKEN"):
        return ["Live checks require DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in environment"]

    return asyncio.run(_run_live_checks_async())


async def _run_live_checks_async():
    """Single async run so one event loop and one broker lifecycle (avoids 'Event loop is closed')."""
    from brokers.broker.entities import Instrument
    from brokers.gateway import BrokerGateway
    from brokers.broker.types import Exchange

    gateway = BrokerGateway.dhan()
    broker = gateway.broker
    await broker.initialize()

    to_date = datetime.now()
    from_date = to_date - timedelta(days=5)
    errors = []

    # NSE
    try:
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="")
        q = await broker._get_quote_async(inst)
        print(f"  NSE RELIANCE LTP: {q.ltp}")
    except Exception as e:
        errors.append(f"NSE quote: {e}")
    try:
        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE, security_id="")
        df = await broker._get_historical_async(inst, from_date, to_date, "1d", False)
        print(f"  NSE historical rows: {len(df)}")
    except Exception as e:
        errors.append(f"NSE historical: {e}")
    try:
        chain = await broker.get_option_chain_async("NIFTY", Exchange.NFO, 0)
        print(f"  NFO NIFTY option chain: {len(chain.calls)} calls, {len(chain.puts)} puts")
    except Exception as e:
        errors.append(f"NFO option chain: {e}")
    try:
        exp = await broker._get_expiry_list_async("NIFTY", Exchange.NFO)
        print(f"  NFO expiries: {len(exp)}")
    except Exception as e:
        errors.append(f"NFO expiries: {e}")

    # MCX
    try:
        inst = Instrument(symbol="GOLD", exchange=Exchange.MCX, security_id="")
        q = await broker._get_quote_async(inst)
        print(f"  MCX GOLD LTP: {q.ltp}")
    except Exception as e:
        errors.append(f"MCX quote: {e}")
    try:
        inst = Instrument(symbol="GOLD", exchange=Exchange.MCX, security_id="")
        df = await broker._get_historical_async(inst, from_date, to_date, "1d", False)
        print(f"  MCX historical rows: {len(df)}")
    except Exception as e:
        errors.append(f"MCX historical: {e}")
    try:
        chain = await broker.get_option_chain_async("GOLD", Exchange.MCX, 0)
        print(f"  MCX GOLD option chain: {len(chain.calls)} calls, {len(chain.puts)} puts")
    except Exception as e:
        errors.append(f"MCX option chain: {e}")
    try:
        exp = await broker._get_expiry_list_async("GOLD", Exchange.MCX)
        print(f"  MCX expiries: {len(exp)}")
    except Exception as e:
        errors.append(f"MCX expiries: {e}")

    # Close broker resources (HTTP client, etc.)
    try:
        await broker.close()
    except Exception:
        pass

    return errors


def main():
    ap = argparse.ArgumentParser(description="E2E verify historical + option chains for NSE and MCX")
    ap.add_argument("--live", action="store_true", help="Use real Dhan API (requires env credentials)")
    args = ap.parse_args()

    mode = "live (Dhan)" if args.live else "paper"
    print(f"Running E2E checks ({mode})...")
    errors = run_live_checks() if args.live else run_paper_checks()

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print(f"Result: {len(errors)} failure(s)")
        sys.exit(1)
    print("Result: all checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
