"""Quick verification of newly implemented stubs against real Dhan API."""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Load .env from project root
load_dotenv("/Users/apple/Downloads/v5-of-glassytrade-ai/.env")

async def test_implementations():
    from brokersv2.infrastructure.dhan_adapter.client import DhanHttpClient, DhanConfig
    from brokersv2.core.types import Exchange
    
    print("=" * 70)
    print("Testing Real Dhan API - Direct Client Tests")
    print("=" * 70)
    
    # Get credentials from env
    client_id = os.environ.get("DHAN_CLIENT_ID", "")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip("'\"")
    
    if not (client_id and access_token):
        print("❌ Missing credentials in .env")
        return
    
    # Create client
    config = DhanConfig(
        client_id=client_id,
        access_token=access_token,
        base_url="https://api.dhan.co/v2",  # Correct API path
    )
    client = DhanHttpClient(config)
    
    print(f"Client ID: {client_id}")
    print(f"Token valid: {len(access_token) > 50}")
    
    # Test 1: Get Quote for NIFTY (index)
    print("\n" + "=" * 70)
    print("Test 1: get_quote() for NIFTY index")
    print("=" * 70)
    
    mapper = None  # Initialize mapper variable for later tests
    
    try:
        from brokersv2.domain.instrument.models import CanonicalInstrument
        from brokersv2.domain.instrument.registry import InstrumentRegistry
        from brokersv2.core.types import Segment, InstrumentType
        
        # Create NIFTY instrument (use FNO segment for index)
        nifty = CanonicalInstrument(
            internal_uid="nifty-test",
            symbol="NIFTY",
            exchange=Exchange.NSE,
            segment=Segment.FNO,  # Index uses FNO segment
            instrument_type=InstrumentType.INDEX,
            lot_size=1,
            tick_size=0.05,
        )
        
        # Create mapper and register NIFTY
        mapper = InstrumentRegistry()
        mapper.register(nifty, security_id="13", exchange_segment="IDX_I")
        
        # Call get_quote
        quote = await client.get_quote(nifty, mapper)
        
        print(f"✅ SUCCESS - Real quote received!")
        print(f"LTP: {quote.ltp}")
        print(f"Bid: {quote.bid}")
        print(f"Ask: {quote.ask}")
        print(f"Volume: {quote.volume}")
        print(f"Open: {quote.open}")
        print(f"High: {quote.high}")
        print(f"Low: {quote.low}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 2: Get Option Chain for NIFTY
    print("\n" + "=" * 70)
    print("Test 2: get_option_chain() for NIFTY")
    print("=" * 70)
    try:
        chain_data = await client.get_option_chain(
            symbol="NIFTY",
            exchange="NSE",
            expiry_index=0,
            mapper=mapper,
        )
        
        print(f"✅ SUCCESS - Option chain received!")
        print(f"Expiry: {chain_data.get('expiry')}")
        print(f"Response keys: {list(chain_data.keys())[:8]}")
        print(f"Has data: {'data' in chain_data}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 3: Get Expiry List
    print("\n" + "=" * 70)
    print("Test 3: Expiry list for NIFTY (via direct API call)")
    print("=" * 70)
    try:
        expiry_payload = {
            "UnderlyingScrip": 13,
            "UnderlyingSeg": "IDX_I",
        }
        
        expiry_data = await client._request(
            "POST",
            "/optionchain/expirylist",
            bucket="non_trading",
            json=expiry_payload,
        )
        
        expiries = expiry_data.get("data", [])
        if isinstance(expiries, dict):
            expiries = expiries.get("data", [])
        
        print(f"✅ SUCCESS - Expiry list received!")
        print(f"Expiry count: {len(expiries)}")
        print(f"First 3 expiries: {expiries[:3]}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    print("\n" + "=" * 70)
    print("Test Complete")
    print("=" * 70)
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(test_implementations())
