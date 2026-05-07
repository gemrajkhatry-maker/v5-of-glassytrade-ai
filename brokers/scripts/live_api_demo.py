"""
Live API examples for historical data and options using the brokers package.

This script demonstrates:
1. Historical OHLCV data retrieval
2. Option chain fetching
3. Expiry list retrieval
"""

import asyncio
import os
from datetime import datetime, timedelta

# Ensure dhanhq is installed
try:
    import dhanhq
except ImportError:
    raise ImportError("pip install dhanhq==2.2.0")

from brokers.broker.dhan.application import DhanBroker, DhanConfig
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange


async def demo_historical_data():
    """Demonstrate historical data retrieval."""
    print("=" * 60)
    print("HISTORICAL DATA DEMO")
    print("=" * 60)
    
    # Create broker from environment (set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN)
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("Skipping: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN env vars")
        return
    
    async with DhanBroker.create(client_id=client_id, access_token=access_token) as broker:
        # Get historical data for RELIANCE
        instrument = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)
        
        from_date = datetime.now() - timedelta(days=30)
        to_date = datetime.now()
        
        print(f"\nFetching 30-day historical data for RELIANCE...")
        df = broker.get_historical(
            instrument=instrument,
            from_date=from_date,
            to_date=to_date,
            interval="1d",
        )
        
        if not df.empty:
            print(f"✓ Retrieved {len(df)} bars")
            print(f"  Columns: {list(df.columns)}")
            print(f"  Latest close: {df['close'].iloc[-1] if 'close' in df.columns else 'N/A'}")
        else:
            print("✗ No data returned")


async def demo_option_chain():
    """Demonstrate option chain retrieval."""
    print("\n" + "=" * 60)
    print("OPTION CHAIN DEMO")
    print("=" * 60)
    
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("Skipping: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN env vars")
        return
    
    async with DhanBroker.create(client_id=client_id, access_token=access_token) as broker:
        print("\nFetching NIFTY option chain...")
        
        try:
            option_chain = broker.get_option_chain(
                underlying="NIFTY",
                exchange=Exchange.NSE,
                expiry_index=0,  # Current week expiry
            )
            
            print(f"✓ Retrieved option chain")
            print(f"  Underlying: {option_chain.underlying}")
            print(f"  Expiry: {option_chain.expiry}")
            
            if hasattr(option_chain, 'ce') and option_chain.ce:
                print(f"  CE strikes: {len(option_chain.ce)}")
            if hasattr(option_chain, 'pe') and option_chain.pe:
                print(f"  PE strikes: {len(option_chain.pe)}")
                
        except Exception as e:
            print(f"✗ Error fetching option chain: {e}")


async def demo_expiry_list():
    """Demonstrate expiry list retrieval."""
    print("\n" + "=" * 60)
    print("EXPIRY LIST DEMO")
    print("=" * 60)
    
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("Skipping: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN env vars")
        return
    
    async with DhanBroker.create(client_id=client_id, access_token=access_token) as broker:
        print("\nFetching NIFTY expiry list...")
        
        try:
            expiries = broker.get_expiry_list(
                underlying="NIFTY",
                exchange=Exchange.NSE,
            )
            
            print(f"✓ Retrieved {len(expiries)} expiry dates")
            for i, expiry in enumerate(expiries[:5]):  # Show first 5
                print(f"  {i+1}. {expiry.strftime('%Y-%m-%d %A')}")
                
        except Exception as e:
            print(f"✗ Error fetching expiry list: {e}")


async def main():
    """Run all demos."""
    print("Brokers Live API Demo")
    print("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables")
    print()
    
    await demo_historical_data()
    await demo_option_chain()
    await demo_expiry_list()
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())