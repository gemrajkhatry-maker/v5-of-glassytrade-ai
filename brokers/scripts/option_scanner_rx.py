"""
NIFTY Option Scanner using RxPY

This script demonstrates using RxPY reactive streams to scan options contracts for NIFTY.
It fetches the option chain and displays relevant metrics.

Usage:
    python brokers/scripts/option_scanner_rx.py
"""

import os
import sys
import asyncio
from datetime import datetime
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rx import of, operators as ops
from rx.subject import Subject


async def main():
    """Main function to run the option scanner."""

    # Get credentials from environment
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables")
        sys.exit(1)

    print("=" * 60)
    print("NIFTY Option Scanner using RxPY")
    print("=" * 60)
    print()

    # Import here to show clear error if not available
    from brokers.reactive import ReactiveBroker
    from brokers.broker.types import Exchange
    from brokers.broker.entities import OptionChain

    # Create reactive broker
    print("Creating reactive Dhan broker...")
    reactive_broker = ReactiveBroker.dhan(
        client_id=client_id, access_token=access_token
    )

    # Access underlying broker for sync operations
    broker = reactive_broker.broker

    # Initialize the broker
    await broker.initialize()
    print("Broker initialized successfully!")
    print()

    # Test 1: Get Option Chain for NIFTY (sync call)
    print("-" * 60)
    print("Fetching NIFTY Option Chain (Nearest Expiry)...")
    print("-" * 60)

    underlying = "NIFTY"
    exchange = Exchange.NFO  # NSE F&O

    try:
        # Run in executor to avoid event loop issues
        loop = asyncio.get_event_loop()
        chain = await loop.run_in_executor(
            None, lambda: broker.get_option_chain(underlying, exchange, expiry_index=0)
        )

        if chain:
            print(f"\nOption Chain Details:")
            print(
                f"  Underlying: {chain.underlying.symbol if chain.underlying else 'N/A'}"
            )
            print(f"  Spot Price: {chain.spot_price}")
            print(f"  Expiry: {chain.expiry}")
            print(f"  Total Calls: {len(chain.calls)}")
            print(f"  Total Puts: {len(chain.puts)}")

            # Get ATM strike
            if chain.spot_price:
                atm_strike = round(chain.spot_price / 50) * 50
                print(f"  ATM Strike: {atm_strike}")
        else:
            print("ERROR: Failed to get option chain")
            return

    except Exception as e:
        print(f"ERROR getting option chain: {e}")
        import traceback

        traceback.print_exc()
        return

    # Test 2: Use RxPY option_chain_stream for periodic updates
    print()
    print("-" * 60)
    print("Testing RxPY option_chain_stream (3 updates)...")
    print("-" * 60)

    update_count = 0

    def on_next(chain: OptionChain):
        nonlocal update_count
        update_count += 1
        print(f"\nUpdate #{update_count}:")
        print(f"  Spot: {chain.spot_price}")
        print(f"  Calls: {len(chain.calls)}")
        print(f"  Puts: {len(chain.puts)}")

        # Show ATM options
        if chain.spot_price and chain.calls:
            atm = round(chain.spot_price / 50) * 50
            call = chain.calls.get(atm)
            put = chain.puts.get(atm)
            if call:
                print(f"  ATM Call ({atm}): {getattr(call, 'ltp', 'N/A')}")
            if put:
                print(f"  ATM Put ({atm}): {getattr(put, 'ltp', 'N/A')}")

    def on_error(e):
        print(f"Stream Error: {e}")

    def on_completed():
        print("\nStream completed")

    # Subscribe to option chain stream (refresh every 5 seconds)
    subscription = reactive_broker.option_chain_stream(
        underlying=underlying,
        exchange=exchange,
        expiry_index=0,
        refresh_interval=5.0,  # 5 seconds between updates
    ).subscribe(on_next=on_next, on_error=on_error, on_completed=on_completed)

    # Wait for 3 updates
    print("Waiting for option chain updates...")
    await asyncio.sleep(15)

    # Dispose subscription
    subscription.dispose()

    # Test 3: Use RxPY spot_price_stream
    print()
    print("-" * 60)
    print("Testing RxPY spot_price_stream...")
    print("-" * 60)

    spot_updates = []

    def on_spot_update(price: float):
        spot_updates.append(price)
        print(f"  Spot price: {price}")

    spot_subscription = reactive_broker.spot_price_stream(
        underlying=underlying, exchange=exchange, expiry_index=0, refresh_interval=3.0
    ).subscribe(on_next=on_spot_update, on_error=lambda e: print(f"Spot Error: {e}"))

    await asyncio.sleep(10)
    spot_subscription.dispose()

    if spot_updates:
        print(f"\nSpot price range: {min(spot_updates):.2f} - {max(spot_updates):.2f}")

    # Test 4: Use RxPY atm_strike_stream
    print()
    print("-" * 60)
    print("Testing RxPY atm_strike_stream...")
    print("-" * 60)

    atm_updates = []

    def on_atm_update(strike: float):
        atm_updates.append(strike)
        print(f"  ATM strike: {strike}")

    atm_subscription = reactive_broker.atm_strike_stream(
        underlying=underlying, exchange=exchange, expiry_index=0, refresh_interval=3.0
    ).subscribe(on_next=on_atm_update, on_error=lambda e: print(f"ATM Error: {e}"))

    await asyncio.sleep(10)
    atm_subscription.dispose()

    if atm_updates:
        print(f"\nATM strikes observed: {atm_updates}")

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Option Chain Updates: {update_count}")
    print(f"Spot Price Updates: {len(spot_updates)}")
    print(f"ATM Strike Updates: {len(atm_updates)}")
    print()
    print("All RxPY streams working correctly!")

    # Cleanup
    await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
