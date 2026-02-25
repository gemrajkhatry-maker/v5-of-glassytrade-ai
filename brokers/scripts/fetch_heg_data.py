"""
Fetch HEG Historical Data Script.

This script fetches one year of historical data for HEG stock from Dhan broker
and saves it to a CSV file.

Usage:
    The script loads credentials from .env file automatically.
    
    Run the script:
        python brokers/scripts/fetch_heg_data.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Add dhanhq_custom to path
dhanhq_custom_path = project_root / "dhanhq_custom"
sys.path.insert(0, str(dhanhq_custom_path))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import pandas as pd


def main():
    """
    Main function to fetch HEG historical data and save to CSV.
    """
    # Check for credentials
    client_id = os.environ.get("DHAN_CLIENT_ID")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("Error: Missing Dhan credentials!")
        print("Please set the following environment variables:")
        print("  - DHAN_CLIENT_ID")
        print("  - DHAN_ACCESS_TOKEN")
        sys.exit(1)
    
    # Import Dhan from dhanhq_custom
    from src import Dhan
    
    # Create Dhan client - it handles everything internally
    dhan = Dhan()
    
    # Define date range (Feb 1, 2025 to Jan 31, 2026)
    from_date = "2025-02-01"
    to_date = "2026-01-31"
    
    print(f"\nFetching HEG historical data...")
    print(f"  Symbol: HEG")
    print(f"  Exchange: NSE (auto-detected)")
    print(f"  From: {from_date}")
    print(f"  To: {to_date}")
    print(f"  Interval: Daily")
    print()
    
    try:
        # Use the simple historical method - Dhan handles security ID resolution internally
        df = dhan.historical(
            symbol="HEG",
            from_date=from_date,
            to_date=to_date,
            interval="1d"  # Daily candles
        )
        
        if df is None or df.empty:
            print("No data returned from API")
            print("This could be due to:")
            print("  - Invalid symbol (HEG may not be found)")
            print("  - Invalid credentials")
            print("  - API connectivity issues")
            sys.exit(1)
        
        # Save to CSV
        output_path = Path("brokers/data/HEG_historical_1year.csv")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        
        print(f"\nSuccess!")
        print(f"  Rows fetched: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        print(f"  Saved to: {output_path}")
        
        # Show date range if available
        if 'timestamp' in df.columns:
            print(f"\nDate range in data:")
            print(f"  First: {df['timestamp'].iloc[0]}")
            print(f"  Last: {df['timestamp'].iloc[-1]}")
        elif 'date' in df.columns:
            print(f"\nDate range in data:")
            print(f"  First: {df['date'].iloc[0]}")
            print(f"  Last: {df['date'].iloc[-1]}")
        
        return output_path
        
    except Exception as e:
        print(f"\nError fetching historical data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    path = main()
    if path:
        print(f"\nCSV file saved at: {path}")
