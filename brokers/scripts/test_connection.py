"""
Test Dhan Connection and Data Retrieval.

This script tests the Dhan broker implementation to verify:
1. Connection works with real credentials
2. Data retrieval works (quotes, historical data, option chain)

Usage:
    # Set environment variables
    export DHAN_CLIENT_ID="your_client_id"
    export DHAN_ACCESS_TOKEN="your_access_token"

    # Run the test
    python brokers/scripts/test_connection.py
"""

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Load .env file like dhanhq_custom does
try:
    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"Loaded .env from: {env_path}")
    else:
        print("Warning: .env file not found")
except ImportError:
    print("Warning: python-dotenv not installed, .env file won't be loaded")

from brokers.broker.dhan import DhanFacade, DhanBroker, DhanConfig


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print(f"{'=' * 60}")


def print_test(test_num: int, description: str):
    """Print test description."""
    print(f"\n{test_num}. {description}")
    print("-" * 40)


def print_success(message: str):
    """Print success message."""
    print(f"   [PASS] {message}")


def print_error(message: str):
    """Print error message."""
    print(f"   [FAIL] {message}")


async def test_connection_async():
    """Test Dhan connection and data retrieval (async version)."""
    print_header("Dhan Connection Test")

    # Check environment variables
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print_error("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must be set")
        print("\nUsage:")
        print("  export DHAN_CLIENT_ID='your_client_id'")
        print("  export DHAN_ACCESS_TOKEN='your_access_token'")
        print("  python brokers/scripts/test_connection.py")
        return False

    # Clean up access token (remove quotes if present)
    if access_token.startswith("'") and access_token.endswith("'"):
        access_token = access_token[1:-1]

    # Mask credentials for display
    print(f"\nCredentials:")
    print(
        f"  Client ID: {client_id[:4]}...{client_id[-2:] if len(client_id) > 6 else '***'}"
    )
    print(
        f"  Access Token: {access_token[:10]}...{access_token[-4:] if len(access_token) > 14 else '***'}"
    )

    # Track test results
    results = {
        "facade_creation": False,
        "ltp_retrieval": False,
        "quote_retrieval": False,
        "historical_data": False,
        "option_chain": False,
    }

    # Test 1: Create facade
    print_test(1, "Creating DhanFacade...")
    try:
        dhan = DhanFacade(client_id=client_id, access_token=access_token)
        print_success("Facade created successfully")
        results["facade_creation"] = True
    except Exception as e:
        print_error(f"Failed to create facade: {e}")
        return False

    # Test 2: Get LTP for TCS (sync API - no async context needed)
    print_test(2, "Testing LTP retrieval for TCS...")
    try:
        ltp = dhan.get_ltp("TCS")
        print_success(f"TCS LTP: Rs.{ltp:.2f}")
        results["ltp_retrieval"] = True
    except Exception as e:
        print_error(f"Failed: {e}")

    # Test 3: Get Quote for RELIANCE
    print_test(3, "Testing Quote retrieval for RELIANCE...")
    try:
        quote = dhan.quote("RELIANCE")
        print_success(f"RELIANCE Quote:")
        print(f"      LTP: Rs.{quote.ltp:.2f}")
        print(f"      Volume: {quote.volume:,}")
        if hasattr(quote, "open") and quote.open:
            print(f"      Open: {quote.open:.2f}")
        if hasattr(quote, "high") and quote.high:
            print(f"      High: {quote.high:.2f}")
        if hasattr(quote, "low") and quote.low:
            print(f"      Low: {quote.low:.2f}")
        results["quote_retrieval"] = True
    except Exception as e:
        print_error(f"Failed: {e}")

    # Test 4: Get Historical Data (last 5 days)
    print_test(4, "Testing Historical Data for TCS (last 5 days)...")
    try:
        to_date = date.today()
        from_date = to_date - timedelta(days=5)
        df = dhan.historical("TCS", from_date, to_date)
        print_success(f"Retrieved {len(df)} candles")
        print(f"      Columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"      First row: {df.iloc[0].to_dict()}")
        results["historical_data"] = True
    except Exception as e:
        print_error(f"Failed: {e}")

    # Test 5: Get Option Chain for NIFTY
    print_test(5, "Testing Option Chain for NIFTY...")
    try:
        chain = dhan.option_chain("NIFTY")
        print_success("Option chain retrieved")
        print(f"      Spot Price: {chain.spot_price}")
        print(f"      Underlying: {chain.underlying}")
        if hasattr(chain, "expiry"):
            print(f"      Expiry: {chain.expiry}")
        if hasattr(chain, "calls") and chain.calls:
            print(f"      Call strikes: {len(chain.calls)}")
        if hasattr(chain, "puts") and chain.puts:
            print(f"      Put strikes: {len(chain.puts)}")
        results["option_chain"] = True
    except Exception as e:
        print_error(f"Failed: {e}")

    # Summary
    print_header("Test Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_flag in results.items():
        status = "[PASS]" if passed_flag else "[FAIL]"
        print(f"  {status} {test_name.replace('_', ' ').title()}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\nAll tests passed! Dhan connection is working correctly.")
        return True
    else:
        print("\nSome tests failed. Check the errors above.")
        return False


def test_connection():
    """Test Dhan connection (sync wrapper)."""
    return asyncio.run(test_connection_async())


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
