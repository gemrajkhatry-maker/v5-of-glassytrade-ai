"""Synthetic Market Data Generator for AMT Validation.

Generates realistic MCX option premium candle series for testing.
Supports 3 session types:
- Balanced (rotation around value)
- OOB Trend Long (out-of-balance bullish)
- Mean Reversion Short (failed breakout, snap back)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from typing import Literal
import os


@dataclass
class SyntheticCandle:
    """A synthetic OHLCV candle for testing."""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float  # buy_vol - sell_vol
    vwap: float = 0.0


@dataclass 
class MarketScenario:
    """A complete market scenario with expected outcomes."""
    name: str
    description: str
    session_type: str  # "BALANCED" | "OOB_TREND" | "MEAN_REVERSION"
    candles: list[dict]
    expected_market_state: str
    expected_bias: str  # "LONG" | "SHORT" | "NEUTRAL"
    expected_setup: str  # "MEAN_REVERSION" | "TREND_MODEL" | "NO_TRADE"
    expected_lvn_present: bool
    expected_aggression: bool
    expected_ib_break: bool
    expected_prior_poc_available: bool
    notes: str = ""


def generate_balanced_session(
    base_price: float = 110.0,
    candles: int = 60,
    range_pct: float = 0.08,  # 8% range
    seed: int = 42,
) -> list[SyntheticCandle]:
    """Generate balanced market rotation (MCX CRUDEOIL 9100 CE style).
    
    Fabio: "70% of time market is in balance, rotating around POC."
    """
    rng = random.Random(seed)
    result = []
    
    low = base_price * (1 - range_pct)
    high = base_price * (1 + range_pct)
    mid = base_price
    
    for i in range(candles):
        # Random walk within range
        open_price = mid + rng.uniform(-range_pct * base_price * 0.3, range_pct * base_price * 0.3)
        close_price = mid + rng.uniform(-range_pct * base_price * 0.3, range_pct * base_price * 0.3)
        
        # Ensure within range
        open_price = max(low, min(high, open_price))
        close_price = max(low, min(high, close_price))
        
        high_price = max(open_price, close_price) + rng.uniform(0, range_pct * base_price * 0.1)
        low_price = min(open_price, close_price) - rng.uniform(0, range_pct * base_price * 0.1)
        
        high_price = min(high, high_price)
        low_price = max(low, low_price)
        
        # Balanced volume and delta
        volume = rng.uniform(800, 1200)
        delta = rng.uniform(-200, 200)  # Balanced delta
        
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(volume, 0),
            delta=round(delta, 0),
            vwap=round(mid, 2),
        ))
    
    return result


def generate_oob_trend_long(
    base_price: float = 110.0,
    candles: int = 60,
    seed: int = 42,
) -> list[SyntheticCandle]:
    """Generate out-of-balance trend LONG (displacement + acceptance).
    
    Fabio: "3+ consecutive candles in one direction, range > 1.5x ATR"
    Structure: balanced start → displacement UP → pullback to LVN → continuation
    """
    rng = random.Random(seed)
    result = []
    
    # Phase 1: Balanced start (10 candles)
    for i in range(10):
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(base_price + rng.uniform(-2, 2), 2),
            high=round(base_price + rng.uniform(0, 3), 2),
            low=round(base_price - rng.uniform(0, 3), 2),
            close=round(base_price + rng.uniform(-2, 2), 2),
            volume=round(rng.uniform(800, 1200), 0),
            delta=round(rng.uniform(-100, 100), 0),
            vwap=round(base_price, 2),
        ))
    
    # Phase 2: Displacement UP (5 candles)
    current = base_price
    for i in range(5):
        open_price = current
        close_price = current + rng.uniform(3, 6)  # Strong up
        high_price = close_price + rng.uniform(0, 2)
        low_price = open_price - rng.uniform(0, 1)
        
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + (i+10) // 12}:{((i+10) % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(rng.uniform(2000, 4000), 0),  # High volume
            delta=round(rng.uniform(500, 1500), 0),   # Bullish delta
            vwap=round((open_price + close_price) / 2, 2),
        ))
        current = close_price
    
    # Phase 3: Pullback to LVN (3 candles)
    lvn_level = base_price + 5  # LVN above original base
    for i in range(3):
        open_price = current
        close_price = current - rng.uniform(1, 3)  # Pullback
        high_price = open_price + rng.uniform(0, 1)
        low_price = min(close_price, lvn_level) - rng.uniform(0, 1)
        
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + (i+15) // 12}:{((i+15) % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(rng.uniform(500, 1000), 0),  # Lower volume pullback
            delta=round(rng.uniform(-300, -100), 0),  # Bearish pullback
            vwap=round((open_price + close_price) / 2, 2),
        ))
        current = close_price
    
    # Phase 4: Continuation (rest of candles)
    for i in range(candles - 18):
        open_price = current
        close_price = current + rng.uniform(0, 2)
        high_price = close_price + rng.uniform(0, 1)
        low_price = open_price - rng.uniform(0, 1)
        
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + (i+18) // 12}:{((i+18) % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(rng.uniform(1000, 2000), 0),
            delta=round(rng.uniform(100, 500), 0),  # Bullish continuation
            vwap=round((open_price + close_price) / 2, 2),
        ))
        current = close_price
    
    return result


def generate_mean_reversion_short(
    base_price: float = 110.0,
    candles: int = 60,
    seed: int = 42,
) -> list[SyntheticCandle]:
    """Generate mean reversion SHORT (failed breakout, snap back).
    
    Fabio: "Failed breakout → snap back to POC"
    Structure: balanced → breakout attempt → FAIL → snap back to POC
    """
    rng = random.Random(seed)
    result = []
    
    # Phase 1: Balanced (20 candles)
    for i in range(20):
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(base_price + rng.uniform(-2, 2), 2),
            high=round(base_price + rng.uniform(0, 3), 2),
            low=round(base_price - rng.uniform(0, 3), 2),
            close=round(base_price + rng.uniform(-2, 2), 2),
            volume=round(rng.uniform(800, 1200), 0),
            delta=round(rng.uniform(-100, 100), 0),
            vwap=round(base_price, 2),
        ))
    
    # Phase 2: Failed breakout attempt UP (5 candles)
    current = base_price + 3
    for i in range(3):
        open_price = current
        close_price = current + rng.uniform(1, 3)  # Attempt up
        high_price = close_price + rng.uniform(1, 2)
        low_price = open_price - rng.uniform(0, 1)
        
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + (i+20) // 12}:{((i+20) % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(rng.uniform(1500, 2500), 0),
            delta=round(rng.uniform(200, 600), 0),  # Bullish attempt
            vwap=round((open_price + close_price) / 2, 2),
        ))
        current = close_price
    
    # Failed breakout candle (closes back inside)
    result.append(SyntheticCandle(
        time=f"2026-03-16T10:25:00",
        open=round(current, 2),
        high=round(current + 1, 2),
        low=round(current - 4, 2),  # Wick down
        close=round(base_price, 2),  # Closes back inside range
        volume=round(rng.uniform(3000, 5000), 0),  # High volume rejection
        delta=round(rng.uniform(-800, -400), 0),  # Bearish rejection
        vwap=round(base_price, 2),
    ))
    current = base_price
    
    # Phase 3: Snap back to POC (rest of candles)
    for i in range(candles - 24):
        open_price = current
        close_price = current - rng.uniform(0, 2)  # Bearish continuation
        high_price = open_price + rng.uniform(0, 1)
        low_price = close_price - rng.uniform(0, 1)
        
        result.append(SyntheticCandle(
            time=f"2026-03-16T{10 + (i+24) // 12}:{((i+24) % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(rng.uniform(1000, 2000), 0),
            delta=round(rng.uniform(-300, -100), 0),
            vwap=round((open_price + close_price) / 2, 2),
        ))
        current = close_price
    
    return result


def generate_all_scenarios() -> dict[str, list[SyntheticCandle]]:
    """Generate all test scenarios."""
    return {
        "balanced": generate_balanced_session(),
        "oob_trend_long": generate_oob_trend_long(),
        "mean_reversion_short": generate_mean_reversion_short(),
    }


def save_scenarios(output_dir: str = "fixtures/candle_data") -> list[str]:
    """Save generated scenarios to JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    
    scenarios = generate_all_scenarios()
    saved_files = []
    
    for name, candles in scenarios.items():
        filepath = os.path.join(output_dir, f"{name}_session.json")
        data = {
            "scenario": name,
            "candle_count": len(candles),
            "candles": [asdict(c) for c in candles],
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        saved_files.append(filepath)
        print(f"✅ Saved {len(candles)} candles to {filepath}")
    
    return saved_files


if __name__ == "__main__":
    files = save_scenarios()
    print(f"\nGenerated {len(files)} scenario files")
