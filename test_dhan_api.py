#!/usr/bin/env python3
"""Test Dhan API connectivity and option chain endpoint."""
import asyncio
import httpx
import json
import os
import sys
from datetime import datetime

# Load env vars
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "1106251237")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

if not DHAN_ACCESS_TOKEN:
    print("❌ ERROR: DHAN_ACCESS_TOKEN not set in environment")
    sys.exit(1)

print("=" * 80)
print("DHAN API CONNECTIVITY TEST")
print("=" * 80)
print(f"Client ID: {DHAN_CLIENT_ID}")
print(f"Token starts with: {DHAN_ACCESS_TOKEN[:20]}...")
print(f"Timestamp: {datetime.now().isoformat()}")
print("=" * 80)

async def test_dhan_api():
    base_url = "https://api.dhan.co"
    
    # Test 1: Basic connectivity
    print("\n[TEST 1] Basic API connectivity...")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            response = await client.get(
                "/api/profile",
                headers={
                    "access-token": DHAN_ACCESS_TOKEN,
                    "x-client-id": DHAN_CLIENT_ID,
                    "Content-Type": "application/json",
                }
            )
            print(f"  Status: {response.status_code}")
            if response.status_code == 200:
                print(f"  ✅ SUCCESS: API is reachable")
                profile = response.json()
                print(f"  Client name: {profile.get('userName', 'N/A')}")
            else:
                print(f"  ❌ FAILED: {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                return False
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        return False
    
    # Test 2: MCX Option Chain - CRUDEOIL
    print("\n[TEST 2] MCX Option Chain - CRUDEOIL...")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            start = datetime.now()
            response = await client.get(
                "/api/options/chain",
                params={
                    "underlying": "CRUDEOIL",
                    "exchange": "MCX",
                    "expiry_index": 0,
                },
                headers={
                    "access-token": DHAN_ACCESS_TOKEN,
                    "x-client-id": DHAN_CLIENT_ID,
                    "Content-Type": "application/json",
                }
            )
            elapsed = (datetime.now() - start).total_seconds()
            print(f"  Status: {response.status_code}")
            print(f"  Time: {elapsed:.2f}s")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ SUCCESS: Got option chain")
                
                # Parse basic info
                if isinstance(data, dict):
                    atm = data.get('atmStrike', 'N/A')
                    expiry = data.get('expiry', 'N/A')
                    spot = data.get('spotPrice', 'N/A')
                    calls = data.get('calls', {})
                    puts = data.get('puts', {})
                    
                    print(f"  ATM Strike: {atm}")
                    print(f"  Expiry: {expiry}")
                    print(f"  Spot Price: {spot}")
                    print(f"  Calls count: {len(calls) if isinstance(calls, dict) else 'N/A'}")
                    print(f"  Puts count: {len(puts) if isinstance(puts, dict) else 'N/A'}")
                    
                    # Show top 3 calls
                    if isinstance(calls, dict) and len(calls) > 0:
                        print(f"\n  Top 3 Calls by strike:")
                        sorted_strikes = sorted(calls.keys(), key=lambda x: float(x))[:3]
                        for strike in sorted_strikes:
                            contract = calls[strike]
                            ltp = contract.get('ltp', 0)
                            oi = contract.get('oi', 0)
                            volume = contract.get('volume', 0)
                            print(f"    Strike {strike}: LTP={ltp}, OI={oi}, Vol={volume}")
                else:
                    print(f"  Unexpected response type: {type(data)}")
                    print(f"  First 500 chars: {str(data)[:500]}")
            else:
                print(f"  ❌ FAILED: {response.status_code}")
                print(f"  Response: {response.text[:500]}")
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 3: MCX Option Chain - NATURALGAS
    print("\n[TEST 3] MCX Option Chain - NATURALGAS...")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            start = datetime.now()
            response = await client.get(
                "/api/options/chain",
                params={
                    "underlying": "NATURALGAS",
                    "exchange": "MCX",
                    "expiry_index": 0,
                },
                headers={
                    "access-token": DHAN_ACCESS_TOKEN,
                    "x-client-id": DHAN_CLIENT_ID,
                    "Content-Type": "application/json",
                }
            )
            elapsed = (datetime.now() - start).total_seconds()
            print(f"  Status: {response.status_code}")
            print(f"  Time: {elapsed:.2f}s")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  ✅ SUCCESS: Got option chain")
                
                if isinstance(data, dict):
                    atm = data.get('atmStrike', 'N/A')
                    expiry = data.get('expiry', 'N/A')
                    spot = data.get('spotPrice', 'N/A')
                    print(f"  ATM Strike: {atm}")
                    print(f"  Expiry: {expiry}")
                    print(f"  Spot Price: {spot}")
            else:
                print(f"  ❌ FAILED: {response.status_code}")
                print(f"  Response: {response.text[:500]}")
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
    
    # Test 4: NSE Option Chain - NIFTY (for comparison)
    print("\n[TEST 4] NSE Option Chain - NIFTY (comparison)...")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            start = datetime.now()
            response = await client.get(
                "/api/options/chain",
                params={
                    "underlying": "NIFTY",
                    "exchange": "NFO",
                    "expiry_index": 0,
                },
                headers={
                    "access-token": DHAN_ACCESS_TOKEN,
                    "x-client-id": DHAN_CLIENT_ID,
                    "Content-Type": "application/json",
                }
            )
            elapsed = (datetime.now() - start).total_seconds()
            print(f"  Status: {response.status_code}")
            print(f"  Time: {elapsed:.2f}s")
            
            if response.status_code == 200:
                print(f"  ✅ SUCCESS: Got NIFTY option chain")
            else:
                print(f"  ❌ FAILED: {response.status_code}")
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_dhan_api())
