"""
Option Scanner Demo with Dhan Broker

This script demonstrates how the OptionScanner uses the Dhan broker
to scan and select the best option contracts for trading.

The scanner workflow:
1. Fetch option chain from Dhan
2. Build candidates with live quotes
3. Apply filters (spread, premium, liquidity)
4. Rank by speed score / Triple-A+ score
5. Select top contracts

Usage:
    python brokers/scripts/demo_option_scanner.py
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
except ImportError:
    pass


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'=' * 70}")
    print(f" {title}")
    print(f"{'=' * 70}\n")


async def run_scanner_demo():
    """Run the option scanner demo."""
    print_section("OPTION SCANNER DEMO - Dhan Broker Integration")

    # Check credentials
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print("ERROR: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environment variables")
        sys.exit(1)

    # =========================================================================
    # Step 1: Initialize Components
    # =========================================================================
    print("Step 1: Initializing components...")
    from app.data.broker_adapter import DhanBrokerAdapter
    from app.core.events import EventBus
    from app.engine.option_scanner import OptionScanner
    from app.config.settings import TradingConfig

    event_bus = EventBus()
    adapter = DhanBrokerAdapter(event_bus=event_bus, paper_mode=True)
    config = TradingConfig()
    scanner = OptionScanner(config=config, event_bus=event_bus)

    print("  - EventBus created")
    print("  - DhanBrokerAdapter created (paper mode)")
    print("  - TradingConfig loaded")
    print("  - OptionScanner created")

    # =========================================================================
    # Step 2: Connect to Dhan
    # =========================================================================
    print("\nStep 2: Connecting to Dhan broker...")
    if not adapter.connect():
        print(f"ERROR: Connection failed - {adapter.last_connect_error}")
        sys.exit(1)
    print("  - Connected successfully")

    # =========================================================================
    # Step 3: Scan Underlyings
    # =========================================================================
    print("\nStep 3: Scanning underlyings...")

    underlyings_to_scan = ["NIFTY", "BANKNIFTY"]

    all_candidates = []
    for underlying in underlyings_to_scan:
        print(f"\n  Scanning {underlying}...")

        try:
            # Fetch candidates from Dhan
            candidates = adapter.fetch_option_candidates(
                underlying=underlying,
                strikes_around=2,
                expiry_index=0,
                exchange="NFO" if underlying in ["NIFTY", "BANKNIFTY"] else "MCX",
                lot_size=0,
            )

            if candidates:
                print(f"    Found {len(candidates)} candidates")
                all_candidates.extend(candidates)
            else:
                print(f"    No candidates found")

        except Exception as e:
            print(f"    ERROR: {e}")

    if not all_candidates:
        print("\nNo candidates found. Exiting...")
        sys.exit(0)

    print(f"\n  Total candidates: {len(all_candidates)}")

    # =========================================================================
    # Step 4: Get Spot Price for Filtering
    # =========================================================================
    print("\nStep 4: Getting spot price for moneyness filtering...")
    spot_price = adapter.get_spot_price("NIFTY", exchange="INDEX")
    if spot_price:
        print(f"  NIFTY Spot: {spot_price:.2f}")
    else:
        spot_price = None
        print("  Spot price not available, skipping moneyness filter")

    # =========================================================================
    # Step 5: Apply Filters and Rank
    # =========================================================================
    print("\nStep 5: Applying filters and ranking...")

    # Filter and rank using scanner
    scored = scanner.filter_and_rank(all_candidates, spot_price=spot_price)

    print(f"  Candidates after filtering: {len(scored)}")

    if not scored:
        print("  No candidates passed filters!")
        sys.exit(0)

    # =========================================================================
    # Step 6: Display Top Candidates
    # =========================================================================
    print("\nStep 6: Top Ranked Candidates")
    print("-" * 70)
    print(f"{'Rank':<5} {'Symbol':<25} {'LTP':<10} {'Score':<10} {'Vol':<10} {'OI':<10}")
    print("-" * 70)

    for i, (candidate, score) in enumerate(scored[:10], 1):
        print(
            f"{i:<5} "
            f"{candidate.contract.symbol:<25} "
            f"{candidate.ltp:<10.2f} "
            f"{score:<10.4f} "
            f"{candidate.volume:<10,} "
            f"{candidate.oi:<10,}"
        )

    print("-" * 70)

    # =========================================================================
    # Step 7: Select Top Contracts
    # =========================================================================
    print("\nStep 7: Selecting top contracts for hotlist...")

    # Use scanner selection logic
    selected = scanner.select_top_contracts(scored, max_contracts=6)

    print(f"  Selected {len(selected)} contracts:")
    for contract in selected:
        print(f"    - {contract.symbol} ({contract.option_type}, Strike: {contract.strike})")

    # =========================================================================
    # Step 8: Show Filter Analysis
    # =========================================================================
    print("\nStep 8: Filter Analysis for Top Candidate")
    print("-" * 70)

    if scored:
        top_candidate, top_score = scored[0]

        print(f"  Symbol: {top_candidate.contract.symbol}")
        print(f"  LTP: Rs.{top_candidate.ltp:.2f}")
        print(f"  Bid-Ask: {top_candidate.bid:.2f} / {top_candidate.ask:.2f}")
        print(f"  Spread: {top_candidate.spread:.2f} ({top_candidate.spread_pct:.2f}%)")
        print(f"  Volume: {top_candidate.volume:,}")
        print(f"  OI: {top_candidate.oi:,}")
        print(f"  OI Change: {top_candidate.oi_change:.2f}%")
        print()
        print(f"  Filter Results:")
        print(f"    - Is Liquid: {top_candidate.is_liquid}")
        print(f"    - Passes Spread Filter: {scanner.passes_spread_filter(top_candidate)}")
        print(f"    - Passes Premium Filter: {scanner.passes_premium_filter(top_candidate)}")
        print(f"    - Passes OI Activity Filter: {scanner.passes_oi_activity_filter(top_candidate)}")
        print()
        print(f"  Scores:")
        print(f"    - Speed Score: {scanner.calculate_speed_score(top_candidate):.4f}")
        print(f"    - Triple-A+ Score: {scanner.calculate_triple_a_plus_score(top_candidate):.4f}")

    # =========================================================================
    # Step 9: Zero Parity Analysis (Optional)
    # =========================================================================
    print("\nStep 9: Zero Parity Analysis")
    print("-" * 70)

    if spot_price and all_candidates:
        parity_by_strike = scanner.calculate_zero_parity(all_candidates, spot_price)

        if parity_by_strike:
            print("  Parity by Strike:")
            for strike, parity in parity_by_strike.items():
                passes = scanner.passes_zero_parity_filter(
                    next((c for c in all_candidates if float(c.contract.strike) == float(strike)), None) or top_candidate,
                    spot_price,
                    parity_by_strike,
                )
                status = "PASS" if passes else "FAIL"
                print(f"    Strike {strike}: Parity = {parity:.2f} [{status}]")
        else:
            print("  No parity data available (need both CE and PE at same strike)")

    # =========================================================================
    # Summary
    # =========================================================================
    print_section("SCANNER DEMO SUMMARY")

    print(f"  Total candidates scanned: {len(all_candidates)}")
    print(f"  Candidates after filters: {len(scored)}")
    print(f"  Contracts selected: {len(selected)}")
    print()
    print("  Scanner + Dhan Integration: WORKING")
    print()
    print("=" * 70)
    print(" Demo completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_scanner_demo())
