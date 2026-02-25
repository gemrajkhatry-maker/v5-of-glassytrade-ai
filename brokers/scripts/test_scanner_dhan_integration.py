"""
Test Option Scanner Integration with Dhan Broker

This script verifies that the OptionScanner (app/engine/option_scanner.py)
works correctly with the Dhan broker integration (brokers/broker/dhan/).

Key Integration Points Tested:
1. DhanBrokerAdapter.fetch_option_candidates() - Scanner data source
2. DhanBrokerAdapter.get_spot_price() - ATM strike calculation
3. DhanBrokerAdapter.build_option_candidate() - Candidate construction
4. Option chain fetching via Dhan API
5. Batch quote optimization for efficiency

Usage:
    python brokers/scripts/test_scanner_dhan_integration.py
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Load .env file
try:
    from dotenv import load_dotenv

    env_path = _project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"Loaded .env from: {env_path}")
    else:
        print("Warning: .env file not found")
except ImportError:
    print("Warning: python-dotenv not installed, .env file won't be loaded")


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'=' * 70}")
    print(f" {title}")
    print(f"{'=' * 70}")


def print_test(test_num: int, description: str):
    """Print test description."""
    print(f"\n{test_num}. {description}")
    print("-" * 70)


def print_success(message: str):
    """Print success message."""
    print(f"   [PASS] {message}")


def print_error(message: str):
    """Print error message."""
    print(f"   [FAIL] {message}")


def print_info(message: str):
    """Print info message."""
    print(f"   [INFO] {message}")


async def test_integration_async():
    """Test the scanner-Dhan integration."""
    print_header("Option Scanner + Dhan Broker Integration Test")

    # Check environment variables
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print_error("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must be set")
        print("\nUsage:")
        print("  export DHAN_CLIENT_ID='your_client_id'")
        print("  export DHAN_ACCESS_TOKEN='your_access_token'")
        print("  python brokers/scripts/test_scanner_dhan_integration.py")
        return False

    # Clean up access token (remove quotes if present)
    if access_token.startswith("'") and access_token.endswith("'"):
        access_token = access_token[1:-1]

    # Mask credentials for display
    print(f"\nCredentials:")
    print(f"  Client ID: {client_id[:4]}...{client_id[-2:] if len(client_id) > 6 else '***'}")
    print(f"  Access Token: {access_token[:10]}...{access_token[-4:] if len(access_token) > 14 else '***'}")

    # Track test results
    results = {
        "adapter_init": False,
        "adapter_connect": False,
        "spot_price_fetch": False,
        "option_chain_fetch": False,
        "candidate_build": False,
        "scanner_compatibility": False,
    }

    # =========================================================================
    # Test 1: Initialize DhanBrokerAdapter
    # =========================================================================
    print_test(1, "Initializing DhanBrokerAdapter...")
    try:
        from app.data.broker_adapter import DhanBrokerAdapter
        from app.core.events import EventBus

        event_bus = EventBus()
        adapter = DhanBrokerAdapter(event_bus=event_bus, paper_mode=True)
        print_success("DhanBrokerAdapter initialized in paper mode")
        results["adapter_init"] = True
    except Exception as e:
        print_error(f"Failed to initialize adapter: {e}")
        import traceback
        traceback.print_exc()
        return False

    # =========================================================================
    # Test 2: Connect to Dhan
    # =========================================================================
    print_test(2, "Connecting to Dhan broker...")
    try:
        connected = adapter.connect()
        if connected:
            print_success("Connected to Dhan broker")
            results["adapter_connect"] = True
        else:
            print_error(f"Connection failed: {adapter.last_connect_error}")
            return False
    except Exception as e:
        print_error(f"Connection error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # =========================================================================
    # Test 3: Get Spot Price (NIFTY)
    # =========================================================================
    print_test(3, "Fetching spot price for NIFTY...")
    try:
        spot_price = adapter.get_spot_price("NIFTY", exchange="INDEX")
        if spot_price and spot_price > 0:
            print_success(f"NIFTY Spot Price: {spot_price:.2f}")
            results["spot_price_fetch"] = True
        else:
            print_error("Failed to get spot price (returned None or 0)")
    except Exception as e:
        print_error(f"Failed to get spot price: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # Test 4: Get Option Chain (NIFTY)
    # =========================================================================
    print_test(4, "Fetching NIFTY option chain...")
    try:
        chain = adapter._get_option_chain_with_retry(
            underlying="NIFTY",
            expiry_index=0,
            exchange="NFO",
        )
        if chain:
            print_success("Option chain fetched successfully")
            print_info(f"  Spot Price: {getattr(chain, 'spot_price', 'N/A')}")
            print_info(f"  ATM Strike: {getattr(chain, 'atm_strike', 'N/A')}")
            print_info(f"  Expiry: {getattr(chain, 'expiry', 'N/A')}")
            print_info(f"  Calls: {len(getattr(chain, 'calls', {}))} strikes")
            print_info(f"  Puts: {len(getattr(chain, 'puts', {}))} strikes")
            results["option_chain_fetch"] = True
        else:
            print_error("Option chain is None")
    except Exception as e:
        print_error(f"Failed to fetch option chain: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # Test 5: Build Option Candidates
    # =========================================================================
    print_test(5, "Building option candidates...")
    try:
        chain = adapter._get_option_chain_with_retry(
            underlying="NIFTY",
            expiry_index=0,
            exchange="NFO",
        )
        if not chain:
            print_error("Cannot build candidates - option chain is None")
        else:
            # Get ATM options
            atm_strike = getattr(chain, 'atm_strike', None)
            if atm_strike:
                calls = getattr(chain, 'calls', {})
                puts = getattr(chain, 'puts', {})

                atm_call = calls.get(atm_strike)
                atm_put = puts.get(atm_strike)

                candidates_built = []
                for opt in [atm_call, atm_put]:
                    if opt:
                        candidate = adapter.build_option_candidate(
                            opt,
                            underlying="NIFTY",
                            exchange="NFO",
                            lot_size=25,
                        )
                        if candidate:
                            candidates_built.append(candidate)
                            print_info(f"  {candidate.contract.symbol}:")
                            print_info(f"    LTP: {candidate.ltp:.2f}")
                            print_info(f"    Bid/Ask: {candidate.bid:.2f} / {candidate.ask:.2f}")
                            print_info(f"    Volume: {candidate.volume:,}")
                            print_info(f"    OI: {candidate.oi:,}")
                            print_info(f"    Spread: {candidate.spread:.2f} ({candidate.spread_pct:.2f}%)")

                if candidates_built:
                    print_success(f"Built {len(candidates_built)} option candidates")
                    results["candidate_build"] = True
                else:
                    print_error("No candidates built successfully")
            else:
                print_error("ATM strike not found in chain")
    except Exception as e:
        print_error(f"Failed to build candidates: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # Test 6: Fetch Option Candidates (Scanner Integration)
    # =========================================================================
    print_test(6, "Testing fetch_option_candidates (Scanner API)...")
    try:
        candidates = adapter.fetch_option_candidates(
            underlying="NIFTY",
            strikes_around=2,
            expiry_index=0,
            exchange="NFO",
            lot_size=25,
        )
        if candidates:
            print_success(f"Fetched {len(candidates)} candidates for scanner")
            # Show top 3 by volume
            sorted_candidates = sorted(candidates, key=lambda c: c.volume, reverse=True)
            for i, c in enumerate(sorted_candidates[:3], 1):
                print_info(f"  #{i} {c.contract.symbol}:")
                print_info(f"      LTP: {c.ltp:.2f}, Vol: {c.volume:,}, OI: {c.oi:,}")
                print_info(f"      Spread: {c.spread_pct:.2f}%, OI Change: {c.oi_change:.2f}%")
            results["scanner_compatibility"] = True
        else:
            print_error("No candidates returned from fetch_option_candidates")
    except Exception as e:
        print_error(f"Failed to fetch candidates: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # Test 7: OptionScanner Integration (Full Test)
    # =========================================================================
    print_test(7, "Testing OptionScanner with Dhan adapter...")
    try:
        from app.engine.option_scanner import OptionScanner, OptionCandidate
        from app.config.settings import TradingConfig

        # Create minimal config for testing
        config = TradingConfig()
        scanner = OptionScanner(config=config, event_bus=event_bus)

        # Test ATM strike calculation
        atm_strike = scanner.get_atm_strike(spot_price=spot_price or 22000, tick_size=50)
        print_info(f"  Calculated ATM Strike: {atm_strike}")

        # Test strike range
        strikes = scanner.get_strike_range(atm_strike=atm_strike, tick_size=50, strikes_around=2)
        print_info(f"  Strike Range: {strikes}")

        # Test filter methods on candidates
        if candidates:
            test_candidate = candidates[0]
            passes_spread = scanner.passes_spread_filter(test_candidate)
            passes_premium = scanner.passes_premium_filter(test_candidate)

            print_info(f"  Sample candidate filter results:")
            print_info(f"    Passes spread filter: {passes_spread}")
            print_info(f"    Passes premium filter: {passes_premium}")

            # Test speed score calculation
            speed_score = scanner.calculate_speed_score(test_candidate)
            print_info(f"    Speed score: {speed_score:.4f}")

            # Test Triple-A+ score
            triple_a_score = scanner.calculate_triple_a_plus_score(test_candidate)
            print_info(f"    Triple-A+ score: {triple_a_score:.4f}")

        print_success("OptionScanner integration working correctly")
        results["scanner_compatibility"] = True
    except Exception as e:
        print_error(f"OptionScanner integration failed: {e}")
        import traceback
        traceback.print_exc()

    # =========================================================================
    # Summary
    # =========================================================================
    print_header("Test Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_flag in results.items():
        status = "[PASS]" if passed_flag else "[FAIL]"
        print(f"  {status} {test_name.replace('_', ' ').title()}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n" + "=" * 70)
        print(" ALL INTEGRATION TESTS PASSED!")
        print(" The OptionScanner is fully compatible with Dhan broker.")
        print("=" * 70)
        return True
    else:
        print("\nSome tests failed. Check the errors above.")
        print("\nNote: Some failures may be due to market hours or API limitations.")
        return False


def test_integration():
    """Test scanner-Dhan integration (sync wrapper)."""
    return asyncio.run(test_integration_async())


if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)
