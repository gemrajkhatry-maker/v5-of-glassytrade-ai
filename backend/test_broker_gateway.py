import os
import asyncio
import sys
import pathlib
from datetime import datetime

# Add project root to sys.path
back_dir = pathlib.Path(__file__).parent.resolve()
root_dir = back_dir.parent.resolve()
sys.path.insert(0, str(back_dir))
sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv
from brokers.gateway import BrokerGateway, Exchange

async def main():
    # Load env from project root
    load_dotenv(root_dir / ".env")
    
    print("Creating BrokerGateway with Dhan configuration...")
    try:
        # BrokerGateway.dhan() auto-loads from env if not provided
        gateway = BrokerGateway.dhan()
        print("✅ Gateway instance created.")
    except Exception as e:
        print(f"❌ Gateway creation FAILED: {e}")
        return

    symbol = "NIFTY"
    print(f"\nChecking quote for {symbol} via Gateway...")
    try:
        # get_quote is sync in the gateway (delegates to broker._run_async)
        quote = gateway.get_quote(symbol, Exchange.NSE)
        if quote and quote.ltp > 0:
            print(f"✅ SUCCESS: {symbol} Quote LTP is {quote.ltp}")
            print(f"   Details: SID={getattr(quote.instrument, 'security_id', '?')}, High={quote.high}, Low={quote.low}")
        else:
            print(f"❌ FAILED: Quote returned LTP=0 or is empty")
    except Exception as e:
        print(f"❌ FAILED: Gateway quote fetch error: {e}")

    # Test historical data via gateway
    print(f"\nChecking history for {symbol} via Gateway...")
    try:
        from_date = datetime.now()
        # get_historical is also sync
        import pandas as pd
        history = gateway.get_historical(
            symbol, 
            Exchange.NSE, 
            from_date=datetime(2026, 4, 9), 
            to_date=datetime(2026, 4, 10),
            interval="5"
        )
        if hasattr(history, "empty") and not history.empty:
            print(f"✅ SUCCESS: Fetched {len(history)} bars of history.")
        else:
            print(f"❌ FAILED: History is empty or invalid type: {type(history)}")
    except Exception as e:
        print(f"❌ FAILED: Gateway history fetch error: {e}")

    gateway.close()

if __name__ == "__main__":
    asyncio.run(main())
