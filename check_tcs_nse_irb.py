#!/usr/bin/env python3
"""
Quick check for IRB (IndusInd Bank) quote on NSE using the BrokerGateway.
"""

import sys
from pathlib import Path

# Ensure repo root is on PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

try:
    from gateway import BrokerGateway
    from shared.entities.models import Exchange
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def main():
    print("Creating paper broker gateway (no real network needed)...")
    gateway = BrokerGateway.paper()
    print("Fetching quote for IRB on NSE...")
    try:
        quote = gateway.get_quote("IRB", Exchange.NSE)
        print("✅ Quote fetched successfully!")
        print(f"Symbol   : {quote.instrument.symbol}")
        print(f"Exchange : {quote.instrument.exchange}")
        print(f"LTP      : {quote.last_price}")
        print(f"Bid      : {quote.bid}")
        print(f"Ask      : {quote.ask}")
        print(f"Timestamp: {quote.timestamp}")
    except Exception as e:
        print(f"Error fetching quote: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()