#!/usr/bin/env python3
"""Test Dhan API using brokers gateway and project venv."""
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brokers.gateway import BrokerGateway, BrokerType
from shared.entities.models import Exchange

print("=" * 80)
print("DHAN API TEST - Using Brokers Gateway")
print("=" * 80)
print(f"Timestamp: {datetime.now().isoformat()}")
print(f"Python: {sys.executable}")
print("=" * 80)

# Test 1: Create Dhan gateway
print("\n[TEST 1] Creating Dhan gateway...")
try:
    gateway = BrokerGateway.dhan()
    print("  ✅ SUCCESS: Gateway created")
    print(f"  Broker type: {type(gateway.raw_broker).__name__}")
except Exception as e:
    print(f"  ❌ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Get MCX Option Chain - CRUDEOIL
print("\n[TEST 2] MCX Option Chain - CRUDEOIL...")
try:
    start = datetime.now()
    chain = gateway.get_option_chain("CRUDEOIL", Exchange.MCX, expiry_index=0)
    elapsed = (datetime.now() - start).total_seconds()
    
    print(f"  Time: {elapsed:.2f}s")
    if chain:
        print(f"  ✅ SUCCESS: Got option chain")
        print(f"  Underlying: {chain.underlying.symbol}")
        print(f"  Exchange: {chain.underlying.exchange}")
        print(f"  ATM Strike: {chain.atm_strike}")
        print(f"  Expiry: {chain.expiry}")
        print(f"  Spot Price: {chain.spot_price}")
        print(f"  Calls count: {len(chain.calls)}")
        print(f"  Puts count: {len(chain.puts)}")
        
        # Show top 3 calls
        if chain.calls:
            print(f"\n  Sample Calls (first 3):")
            for i, (strike, contract) in enumerate(sorted(chain.calls.items())[:3]):
                print(f"    Strike {strike}: LTP={contract.ltp}, OI={contract.oi}, Vol={contract.volume}")
    else:
        print(f"  ❌ FAILED: Got None response")
except Exception as e:
    print(f"  ❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Get MCX Option Chain - NATURALGAS
print("\n[TEST 3] MCX Option Chain - NATURALGAS...")
try:
    start = datetime.now()
    chain = gateway.get_option_chain("NATURALGAS", Exchange.MCX, expiry_index=0)
    elapsed = (datetime.now() - start).total_seconds()
    
    print(f"  Time: {elapsed:.2f}s")
    if chain:
        print(f"  ✅ SUCCESS: Got option chain")
        print(f"  ATM Strike: {chain.atm_strike}")
        print(f"  Expiry: {chain.expiry}")
        print(f"  Spot Price: {chain.spot_price}")
    else:
        print(f"  ❌ FAILED: Got None response")
except Exception as e:
    print(f"  ❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Get NSE Option Chain - NIFTY (for comparison)
print("\n[TEST 4] NSE Option Chain - NIFTY (comparison)...")
try:
    start = datetime.now()
    chain = gateway.get_option_chain("NIFTY", Exchange.NSE, expiry_index=0)
    elapsed = (datetime.now() - start).total_seconds()
    
    print(f"  Time: {elapsed:.2f}s")
    if chain:
        print(f"  ✅ SUCCESS: Got NIFTY option chain")
        print(f"  ATM Strike: {chain.atm_strike}")
        print(f"  Expiry: {chain.expiry_date}")
    else:
        print(f"  ❌ FAILED: Got None response")
except Exception as e:
    print(f"  ❌ ERROR: {e}")

# Cleanup
print("\n[CLEANUP] Closing gateway...")
try:
    gateway.close()
    print("  ✅ Gateway closed")
except Exception as e:
    print(f"  ⚠️  Error closing: {e}")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
