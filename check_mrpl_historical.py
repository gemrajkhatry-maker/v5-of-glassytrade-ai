#!/usr/bin/env python3
"""
Fetch historical data for MRPL on NSE using Dhan broker gateway.
MRPL = Mangalore Refinery & Petrochemicals Ltd
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

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
        gateway = BrokerGateway.dhan()
    except Exception as e:
        print(f"Failed to create Dhan gateway: {e}")
        sys.exit(1)

    # Last 30 days
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=30)

    print(f"Fetching historical data for MRPL on NSE from {start_date.date()} to {end_date.date()}")
    print("Interval: 1d")
    try:
        df = gateway.get_historical(
            symbol="MRPL",
            exchange=Exchange.NSE,
            from_date=start_date,
            to_date=end_date,
            interval="1d",
            include_oi=False,
        )
        print(f"\nSuccess! Retrieved {len(df)} rows.")
        if hasattr(df, 'head'):
            print("\nFirst 5 rows:")
            print(df.head().to_string())
            print("\nLast 5 rows:")
            print(df.tail().to_string())
    except Exception as e:
        print(f"\nError fetching historical data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()