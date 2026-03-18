"""Synthetic Market Data Generator for AMT Validation.

Generates realistic market scenarios to test the AMT pipeline accuracy.
Each scenario represents a known market state with expected outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import random


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

    @property
    def taker_buy_volume(self) -> float:
        return max(0, (self.volume + self.delta) / 2)


@dataclass
class MarketScenario:
    """A complete market scenario with expected AMT outcomes."""
    name: str
    description: str
    candles: list[SyntheticCandle]
    expected_market_state: str  # "BALANCED" | "IMBALANCED"
    expected_bias: str  # "LONG" | "SHORT" | "NEUTRAL"
    expected_setup: str  # "MEAN_REVERSION" | "TREND_MODEL" | "NO_TRADE"
    expected_lvn_present: bool
    expected_aggression: bool
    notes: str = ""


def generate_balanced_rotation(
    base_price: float = 25000,
    candles: int = 30,
    range_pct: float = 0.01,  # 1% range
    seed: int = 42,
) -> list[SyntheticCandle]:
    """Generate balanced market rotation around base price.
    
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
        
        # Balanced volume
        volume = rng.uniform(800, 1200)
        delta = rng.uniform(-200, 200)  # Balanced delta
        
        result.append(SyntheticCandle(
            time=f"2026-03-14T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(volume, 0),
            delta=round(delta, 0),
            vwap=round(mid, 2),
        ))
    
    return result


def generate_displacement_leg(
    base_price: float = 25000,
    direction: Literal["UP", "DOWN"] = "UP",
    candles: int = 5,
    magnitude_pct: float = 0.02,  # 2% move
    seed: int = 42,
) -> list[SyntheticCandle]:
    """Generate a displacement leg (strong directional move).
    
    Fabio: "3+ consecutive candles in one direction, range > 1.5x ATR"
    """
    rng = random.Random(seed)
    result = []
    
    move_per_candle = (base_price * magnitude_pct) / candles
    current = base_price
    
    for i in range(candles):
        if direction == "UP":
            open_price = current
            close_price = current + move_per_candle + rng.uniform(0, move_per_candle * 0.2)
            high_price = close_price + rng.uniform(0, move_per_candle * 0.3)
            low_price = open_price - rng.uniform(0, move_per_candle * 0.1)
            delta = rng.uniform(500, 1500)  # Bullish delta
        else:
            open_price = current
            close_price = current - move_per_candle - rng.uniform(0, move_per_candle * 0.2)
            low_price = close_price - rng.uniform(0, move_per_candle * 0.3)
            high_price = open_price + rng.uniform(0, move_per_candle * 0.1)
            delta = rng.uniform(-1500, -500)  # Bearish delta
        
        volume = rng.uniform(2000, 4000)  # High volume
        
        result.append(SyntheticCandle(
            time=f"2026-03-14T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(volume, 0),
            delta=round(delta, 0),
            vwap=round((open_price + close_price) / 2, 2),
        ))
        
        current = close_price
    
    return result


def generate_pullback_to_lvn(
    base_price: float = 25000,
    direction: Literal["LONG", "SHORT"] = "LONG",
    lvn_price: float = 24800,
    candles: int = 3,
    seed: int = 42,
) -> list[SyntheticCandle]:
    """Generate pullback candles to LVN (low volume node).
    
    Fabio: "Wait for pullback into LVN — that's your entry zone."
    """
    rng = random.Random(seed)
    result = []
    
    current = base_price
    target = lvn_price
    
    for i in range(candles):
        # Move toward LVN
        if direction == "LONG":
            close_price = current - abs(current - target) / (candles - i + 1)
            delta = rng.uniform(-300, -100)  # Bearish pullback
        else:
            close_price = current + abs(target - current) / (candles - i + 1)
            delta = rng.uniform(100, 300)  # Bullish pullback
        
        open_price = current
        high_price = max(open_price, close_price) + rng.uniform(0, 10)
        low_price = min(open_price, close_price) - rng.uniform(0, 10)
        
        volume = rng.uniform(500, 1000)  # Lower volume (pullback)
        
        result.append(SyntheticCandle(
            time=f"2026-03-14T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(volume, 0),
            delta=round(delta, 0),
            vwap=round((open_price + close_price) / 2, 2),
        ))
        
        current = close_price
    
    return result


def generate_aggression_candle(
    price: float = 24800,
    direction: Literal["BUY", "SELL"] = "BUY",
    magnitude: float = 50,
    seed: int = 42,
) -> SyntheticCandle:
    """Generate an aggressive candle (large executed orders).
    
    Fabio: "When you see aggression, that's your trigger."
    """
    rng = random.Random(seed)
    
    if direction == "BUY":
        open_price = price
        close_price = price + magnitude
        high_price = close_price + rng.uniform(0, magnitude * 0.3)
        low_price = open_price - rng.uniform(0, magnitude * 0.1)
        delta = rng.uniform(1000, 3000)  # Strong bullish delta
    else:
        open_price = price
        close_price = price - magnitude
        low_price = close_price - rng.uniform(0, magnitude * 0.3)
        high_price = open_price + rng.uniform(0, magnitude * 0.1)
        delta = rng.uniform(-3000, -1000)  # Strong bearish delta
    
    volume = rng.uniform(5000, 10000)  # Very high volume (aggression)
    
    return SyntheticCandle(
        time="2026-03-14T10:30:00",
        open=round(open_price, 2),
        high=round(high_price, 2),
        low=round(low_price, 2),
        close=round(close_price, 2),
        volume=round(volume, 0),
        delta=round(delta, 0),
        vwap=round((open_price + close_price) / 2, 2),
    )


# ============================================================================
# COMPLETE MARKET SCENARIOS
# ============================================================================

def get_scenario_trend_long_at_lvn() -> MarketScenario:
    """Scenario: Trending market, pullback to LVN, aggression confirms LONG.
    
    Expected: Valid LONG entry (Trend Continuation model)
    """
    base = 25000
    
    # Phase 1: Displacement leg UP
    displacement = generate_displacement_leg(base, "UP", candles=5, magnitude_pct=0.02)
    
    # Phase 2: Pullback to LVN (around 25100)
    pullback_start = displacement[-1].close
    pullback = generate_pullback_to_lvn(pullback_start, "LONG", 25100, candles=3)
    
    # Phase 3: Aggression candle (confirmation)
    aggression = generate_aggression_candle(pullback[-1].close, "BUY", magnitude=30)
    
    all_candles = displacement + pullback + [aggression]
    
    return MarketScenario(
        name="TREND_LONG_AT_LVN",
        description="Displacement UP → Pullback to LVN → BUY aggression → LONG entry",
        candles=all_candles,
        expected_market_state="IMBALANCED",
        expected_bias="LONG",
        expected_setup="TREND_MODEL",
        expected_lvn_present=True,
        expected_aggression=True,
        notes="Second drive setup - high probability",
    )


def get_scenario_balanced_mean_reversion() -> MarketScenario:
    """Scenario: Balanced market, failed breakout, snap back to POC.
    
    Expected: Valid SHORT entry (Mean Reversion model)
    """
    # Generate balanced rotation
    balanced = generate_balanced_rotation(25000, candles=20, range_pct=0.01)
    
    # Add failed breakout candle
    last_close = balanced[-1].close
    failed_breakout = SyntheticCandle(
        time="2026-03-14T11:00:00",
        open=last_close + 100,
        high=last_close + 200,  # Break above range
        low=last_close - 50,
        close=last_close + 20,  # Closed back inside
        volume=3000,
        delta=-500,  # Bearish rejection
        vwap=last_close + 50,
    )
    
    # Aggressive sell candle (snap back)
    snap_back = SyntheticCandle(
        time="2026-03-14T11:05:00",
        open=last_close + 20,
        high=last_close + 30,
        low=last_close - 80,
        close=last_close - 40,
        volume=4000,
        delta=-1200,  # Strong selling
        vwap=last_close - 20,
    )
    
    all_candles = balanced + [failed_breakout, snap_back]
    
    return MarketScenario(
        name="BALANCED_MEAN_REVERSION",
        description="Balanced → Failed breakout → Snap back to POC → SHORT entry",
        candles=all_candles,
        expected_market_state="BALANCED",
        expected_bias="SHORT",
        expected_setup="MEAN_REVERSION",
        expected_lvn_present=False,
        expected_aggression=True,
        notes="Mean reversion - snap back to value",
    )


def get_scenario_no_trade_choppy() -> MarketScenario:
    """Scenario: Choppy market, no clear direction, mixed signals.
    
    Expected: NO TRADE (conditions not aligned)
    """
    rng = random.Random(123)
    candles = []
    price = 25000
    
    for i in range(30):
        # Random choppy movement
        change = rng.uniform(-50, 50)
        open_price = price
        close_price = price + change
        high_price = max(open_price, close_price) + rng.uniform(0, 20)
        low_price = min(open_price, close_price) - rng.uniform(0, 20)
        
        # Mixed volume and delta
        volume = rng.uniform(500, 1500)
        delta = rng.uniform(-300, 300)
        
        candles.append(SyntheticCandle(
            time=f"2026-03-14T{10 + i // 12}:{(i % 12) * 5:02d}:00",
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=round(volume, 0),
            delta=round(delta, 0),
            vwap=round(price, 2),
        ))
        
        price = close_price
    
    return MarketScenario(
        name="NO_TRADE_CHOPPY",
        description="Choppy market, mixed signals, no clear direction",
        candles=candles,
        expected_market_state="BALANCED",
        expected_bias="NEUTRAL",
        expected_setup="NO_TRADE",
        expected_lvn_present=False,
        expected_aggression=False,
        notes="System should stay flat - no clear setup",
    )


def get_scenario_first_drive_fakeout() -> MarketScenario:
    """Scenario: First drive at level (should NOT trade per Fabio).
    
    Expected: NO TRADE (first drive - wait for second)
    """
    # Strong move up
    move_up = generate_displacement_leg(25000, "UP", candles=4, magnitude_pct=0.015)
    
    # First touch at resistance (no pullback yet)
    first_touch = SyntheticCandle(
        time="2026-03-14T10:20:00",
        open=move_up[-1].close,
        high=move_up[-1].close + 20,
        low=move_up[-1].close - 10,
        close=move_up[-1].close + 5,
        volume=2000,
        delta=300,
        vwap=move_up[-1].close,
    )
    
    return MarketScenario(
        name="FIRST_DRIVE_FAKEOUT",
        description="First touch at resistance - NOT second drive",
        candles=move_up + [first_touch],
        expected_market_state="IMBALANCED",
        expected_bias="NEUTRAL",
        expected_setup="NO_TRADE",
        expected_lvn_present=False,
        expected_aggression=True,
        notes="Fabio: Don't take first drive - wait for second",
    )


# ============================================================================
# SCENARIO REGISTRY
# ============================================================================

ALL_SCENARIOS = [
    get_scenario_trend_long_at_lvn(),
    get_scenario_balanced_mean_reversion(),
    get_scenario_no_trade_choppy(),
    get_scenario_first_drive_fakeout(),
]
