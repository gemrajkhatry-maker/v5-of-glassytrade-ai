#!/usr/bin/env python3
"""
Fetch historical data for TCS on NSE using Dhan broker gateway.
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add repo root to sys.path so we can import shared and gateway
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
    print("Creating Dhan broker gateway...")
    try:
        gateway = BrokerGateway.dhan()   # reads .env for credentials
    except Exception as e:
        print(f"Failed to create Dhan gateway: {e}")
        print("Make sure DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN are set in .env")
        sys.exit(1)

    # Define date range: last 30 days
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=30)

    print(f"Fetching historical data for TCS on NSE from {start_date.date()} to {end_date.date()}")
    print("Interval: 1d")
    try:
        # The gateway's get_historical returns a pandas DataFrame (or similar)
        df = gateway.get_historical(
            symbol="TCS",
            exchange=Exchange.NSE,
            from_date=start_date,
            to_date=end_date,
            interval="1d",
            include_oi=False,
        )
        print(f"\nSuccess! Retrieved {len(df)} rows.")
        # If it's a DataFrame, show head and tail
        if hasattr(df, 'head'):
            print("\nFirst 5 rows:")
            print(df.head().to_string())
            print("\nLast 5 rows:")
            print(df.tail().to_string())
        else:
            # fallback: try to iterate
            print("Data (first 5 rows):")
            for i, row in enumerate(df):
                if i >= 5:
                    break
                print(row)
    except Exception as e:
        print(f"\nError fetching historical data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
