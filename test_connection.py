#!/usr/bin/env python3
"""
Simple sanity‑check for the broker gateway.

* Uses the PaperBroker implementation (no external network required).
* Calls `get_quote` to obtain a dummy Quote.
* Calls `place_order` in dry‑run mode to verify the order pipeline.
"""

import sys
from gateway import BrokerGateway
from shared.entities.models import Exchange

def test_paper_quote():
    """Retrieve a dummy quote from the paper broker."""
    print("\n=== Testing PAPER BROKER (no external network needed) ===")
    try:
        gateway = BrokerGateway.paper()
        quote = gateway.get_quote("NIFTY", Exchange.NSE)
        print("[+] Quote retrieved successfully!")
        print(f"   Symbol : {quote.instrument.symbol}")
        print(f"   Bid    : {quote.bid_price}")
        print(f"   Ask    : {quote.ask_price}")
        print(f"   Last LTP: {quote.last_price}")
        return True
    except Exception as exc:
        print("[!] Failed to get a quote:", exc, file=sys.stderr)
        return False

def test_dry_run_order():
    """Place a dry‑run order (intercepted, mocked, never hits the network)."""
    print("\n=== Testing DRY‑RUN ORDER PLACEMENT ===")
    try:
        gateway = BrokerGateway.paper()
        order = gateway.place_order(
            symbol="NIFTY",
            side="BUY",
            quantity=1,
            order_type="MARKET",
            price=0,
        )
        print("[+] Dry‑run order placed, order_id:", order.order_id)
        return True
    except Exception as exc:
        print("[!] Dry‑run order failed:", exc, file=sys.stderr)
        return False

if __name__ == "__main__":
    success1 = test_paper_quote()
    success2 = test_dry_run_order()

    if success1 and success2:
        print("\n✅ All connection checks passed – the broker gateway is healthy.")
    else:
        print("\n❌ One or more checks failed – see the error messages above.")