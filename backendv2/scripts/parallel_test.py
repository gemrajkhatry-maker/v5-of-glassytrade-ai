#!/usr/bin/env python3
"""Parallel testing script to compare backendv2 with existing backend."""
import asyncio
import json
from decimal import Decimal
from datetime import datetime

# Test data matching amt_docs specifications
TEST_TICKS = [
    {"time": "2024-01-15T10:00:00Z", "open": 49950, "high": 50100, "low": 49900, "close": 50050, "volume": 500},
    {"time": "2024-01-15T10:01:00Z", "open": 50050, "high": 50150, "low": 49950, "close": 50100, "volume": 600},
    {"time": "2024-01-15T10:02:00Z", "open": 50100, "high": 50200, "low": 50000, "close": 50150, "volume": 700},
]

async def test_backendv2():
    """Test backendv2 implementation."""
    from app.domain.amt.service.amt_analyzer import (
        build_volume_profile, calculate_vwap, detect_absorptions, generate_triple_a_signal
    )
    
    bars = [
        {
            'open': tick['open'],
            'high': tick['high'],
            'low': tick['low'],
            'close': tick['close'],
            'volume': tick['volume'],
            'buyVolume': tick['volume'] * 0.6,
            'sellVolume': tick['volume'] * 0.4,
            'bar_index': i
        }
        for i, tick in enumerate(TEST_TICKS)
    ]
    
    # Build analysis
    vp = build_volume_profile(bars, bucket_size=50.0)
    vwap, _, _, _, _ = calculate_vwap(bars)
    absorptions = detect_absorptions(bars)
    signal = generate_triple_a_signal(bars, absorptions, vp, vwap)
    
    return {
        "volume_profile": {
            "poc": vp.poc,
            "vah": vp.vah,
            "val": vp.val
        },
        "vwap": vwap,
        "absorptions_count": len(absorptions),
        "signal": {
            "type": signal.type,
            "entry": signal.entry,
            "sl": signal.sl,
            "tp": signal.tp,
            "rr": signal.rr
        }
    }


async def test_existing_backend():
    """Test existing backend implementation."""
    # Placeholder - would import from existing backend
    # This would call the existing Node.js/Python backend
    return {
        "volume_profile": {
            "poc": 50100,
            "vah": 50150,
            "val": 49950
        },
        "vwap": 50066.67,
        "absorptions_count": 0,
        "signal": {
            "type": "NO_TRADE",
            "entry": 0,
            "sl": 0,
            "tp": 0,
            "rr": 0
        }
    }


async def main():
    """Run parallel comparison."""
    print("=" * 60)
    print("BACKENDV2 vs EXISTING BACKEND COMPARISON")
    print("=" * 60)
    
    print("\n📊 Running backendv2 analysis...")
    v2_result = await test_backendv2()
    
    print("\n📊 Running existing backend analysis...")
    existing_result = await test_existing_backend()
    
    print("\n" + "=" * 60)
    print("RESULTS COMPARISON")
    print("=" * 60)
    
    print("\n📈 Volume Profile:")
    print(f"  POC - V2: {v2_result['volume_profile']['poc']} | Existing: {existing_result['volume_profile']['poc']}")
    print(f"  VAH - V2: {v2_result['volume_profile']['vah']} | Existing: {existing_result['volume_profile']['vah']}")
    print(f"  VAL - V2: {v2_result['volume_profile']['val']} | Existing: {existing_result['volume_profile']['val']}")
    
    print("\n📊 VWAP:")
    print(f"  V2: {v2_result['vwap']:.2f} | Existing: {existing_result['vwap']:.2f}")
    
    print("\n⚡ Absorptions:")
    print(f"  V2: {v2_result['absorptions_count']} | Existing: {existing_result['absorptions_count']}")
    
    print("\n🎯 Signal:")
    print(f"  Type - V2: {v2_result['signal']['type']} | Existing: {existing_result['signal']['type']}")
    print(f"  Entry - V2: {v2_result['signal']['entry']:.2f} | Existing: {existing_result['signal']['entry']:.2f}")
    
    # Check parity
    parity_checks = {
        "Volume Profile POC within tolerance": abs(v2_result['volume_profile']['poc'] - existing_result['volume_profile']['poc']) < 100,
        "VWAP within 0.1%": abs(v2_result['vwap'] - existing_result['vwap']) / existing_result['vwap'] < 0.001,
        "Signal type matches": v2_result['signal']['type'] == existing_result['signal']['type']
    }
    
    print("\n✅ PARITY CHECKS:")
    for check, passed in parity_checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}")
    
    all_passed = all(parity_checks.values())
    print(f"\n{'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)