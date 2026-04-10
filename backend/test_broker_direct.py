import os
import asyncio
import sys
import pathlib

# Add current directory and project root to sys.path
back_dir = pathlib.Path(__file__).parent.resolve()
root_dir = back_dir.parent.resolve()
sys.path.insert(0, str(back_dir))
sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv
from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter

async def main():
    load_dotenv(root_dir / ".env")
    
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("ERROR: DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not set in .env")
        return

    adapter = DhanMarketDataAdapter(
        client_id=client_id,
        access_token=access_token,
    )
    
    print("Initializing adapter (this will refresh instrument cache)...")
    try:
        await adapter._ensure_initialized()
        print("Broker initialised successfully.")
    except Exception as e:
        print(f"Broker initialization FAILED: {e}")
        return
    
    symbol = "NIFTY"
    print(f"\nChecking resolution for {symbol}...")
    try:
        instrument = await adapter.resolve_symbol(symbol)
        print(f"✅ RESOLVED: {symbol} -> SID={instrument.security_id}, Segment={instrument.exchange_segment}, Type={instrument.instrument_type}")
    except Exception as e:
        print(f"❌ RESOLUTION FAILED: {e}")

    print(f"\nChecking history for {symbol}...")
    try:
        history = await adapter.fetch_history(symbol, limit=5)
        if history:
            print(f"✅ SUCCESS: Fetched {len(history)} candles. Last close: {history[-1].close}")
        else:
            print(f"❌ FAILED: No history returned for {symbol}")
    except Exception as e:
        print(f"❌ FAILED: History fetch error: {e}")
        
    print(f"\nChecking LTP for {symbol}...")
    try:
        ltp = adapter.get_ltp(symbol)
        if ltp > 0:
            print(f"✅ SUCCESS: LTP is {ltp}")
        else:
            print(f"❌ FAILED: LTP is {ltp}")
    except Exception as e:
        print(f"❌ FAILED: LTP fetch error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
