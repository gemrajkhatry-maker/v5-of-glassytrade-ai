#!/usr/bin/env python3
"""
Quick check for TCS quote using paper broker.
"""

import sys
import os

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from gateway import BrokerGateway
    from shared.entities.models import Exchange
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def main():
    print("Creating paper broker gateway...")
    gateway = BrokerGateway.paper()
    print("Fetching quote for TCS on NSE...")
    try:
        quote = gateway.get_quote("TCS", Exchange.NSE)
        print("Success!")
        print(f"  Symbol: {quote.instrument.symbol}")
        print(f"  Exchange: {quote.instrument.exchange}")
        print(f"  LTP: {quote.ltp}")
        print(f"  Bid: {quote.bid}")
        print(f"  Ask: {quote.ask}")
        print(f"  Timestamp: {quote.timestamp}")
    except Exception as e:
        print(f"Error getting quote: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
