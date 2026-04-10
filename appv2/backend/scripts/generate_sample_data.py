"""Sample Data Generator — creates realistic NIFTY / CRUDEOIL tick data.

Generates tick-level data with known auction patterns:
- Balanced session (rotation around POC)
- Imbalanced breakout (displacement + acceptance)
- Failed breakout (rejection + snap-back)
- LVN zones (acceleration areas)
- CVD pressure (buying/selling pressure)
- Opening noise, primary setup, midday, power hour

Output: OHLC candles at 1-minute resolution for full trading day.
"""

from __future__ import annotations

import math
import random
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta

random.seed(42)  # Reproducible


@dataclass
class MarketPhase:
    """Defines a market phase with characteristics."""
    name: str
    start_minute: int
    end_minute: int
    base_price: float
    volatility: float
    trend: float  # Per-minute drift
    balance: bool  # Is market balanced?


@dataclass
class GeneratedCandle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float  # Buy - Sell volume


class SampleDataGenerator:
    """Generates realistic tick data with known auction patterns."""

    def __init__(
        self,
        symbol: str = "NIFTY",
        base_price: float = 23400.0,
        tick_size: float = 0.05,
        date: str = "2026-04-09",
    ):
        self.symbol = symbol
        self.base_price = base_price
        self.tick_size = tick_size
        self.date = date
        self._candles: list[GeneratedCandle] = []

    def generate_balanced_day(self) -> list[GeneratedCandle]:
        """Generate a balanced (rotational) trading day.

        Price rotates around POC with failed breakouts.
        Typical of London session / midday NSE.
        """
        self._candles = []
        poc = self.base_price
        vah = poc + 80  # Value area high
        val = poc - 80  # Value area low

        # Opening noise (09:15-09:30)
        self._generate_phase(
            name="OPENING",
            start=0, end=15,
            base=poc, volatility=40, trend=0,
            balance=True,
        )

        # Balanced rotation (09:30-11:30)
        self._generate_phase(
            name="PRIMARY_BALANCED",
            start=15, end=135,
            base=poc, volatility=30, trend=0,
            balance=True,
        )

        # Midday consolidation (11:30-14:00)
        self._generate_phase(
            name="MIDDAY",
            start=135, end=285,
            base=poc, volatility=20, trend=0,
            balance=True,
        )

        # Failed breakout attempt (14:00-14:30)
        self._generate_failed_breakout(
            start=285, end=315,
            base=poc, vah=vah, val=val,
        )

        # Power hour (14:30-15:15)
        self._generate_phase(
            name="POWER_HOUR",
            start=315, end=360,
            base=poc, volatility=25, trend=0,
            balance=True,
        )

        # Close (15:15-15:30)
        self._generate_phase(
            name="CLOSE",
            start=360, end=375,
            base=poc, volatility=15, trend=0,
            balance=True,
        )

        return self._candles

    def generate_imbalanced_day(self) -> list[GeneratedCandle]:
        """Generate a trending (imbalanced) day.

        Price breaks out of balance and trends in one direction.
        Typical of strong news days.
        """
        self._candles = []
        poc = self.base_price
        vah = poc + 60
        val = poc - 60

        # Opening noise
        self._generate_phase(
            name="OPENING",
            start=0, end=15,
            base=poc, volatility=50, trend=0,
            balance=True,
        )

        # Balanced start (09:30-10:00)
        self._generate_phase(
            name="PRIMARY_BALANCED",
            start=15, end=45,
            base=poc, volatility=25, trend=0,
            balance=True,
        )

        # Imbalanced breakout (10:00-11:30)
        self._generate_imbalanced_breakout(
            name="BREAKOUT",
            start=45, end=135,
            base=poc, vah=vah, val=val,
            direction="UP",
        )

        # Continuation with shallow pullbacks (11:30-14:00)
        new_poc = poc + 150
        self._generate_phase(
            name="CONTINUATION",
            start=135, end=285,
            base=new_poc, volatility=20, trend=0.1,
            balance=False,
        )

        # Power hour continuation (14:00-15:15)
        self._generate_phase(
            name="POWER_HOUR",
            start=285, end=360,
            base=new_poc + 30, volatility=25, trend=0.05,
            balance=False,
        )

        # Close
        self._generate_phase(
            name="CLOSE",
            start=360, end=375,
            base=new_poc + 40, volatility=15, trend=0,
            balance=False,
        )

        return self._candles

    def _generate_phase(
        self,
        name: str,
        start: int,
        end: int,
        base: float,
        volatility: float,
        trend: float,
        balance: bool,
    ) -> None:
        """Generate candles for a market phase."""
        price = base
        if self._candles:
            price = self._candles[-1].close

        for minute in range(start, end):
            hour = 9 + minute // 60
           min_val = minute % 60
            time_str = f"{self.date}T{hour:02d}:{min:02d}:00"

            # Generate OHLC with noise
            noise = random.gauss(0, volatility * 0.3)
            trend_move = trend

            # Mean reversion if balanced
            if balance:
                reversion = (base - price) * 0.02
            else:
                reversion = 0

            open_price = price
            close_price = price + noise + trend_move + reversion
            high_price = max(open_price, close_price) + abs(random.gauss(0, volatility * 0.2))
            low_price = min(open_price, close_price) - abs(random.gauss(0, volatility * 0.2))

            # Round to tick size
            open_price = round(open_price / self.tick_size) * self.tick_size
            high_price = round(high_price / self.tick_size) * self.tick_size
            low_price = round(low_price / self.tick_size) * self.tick_size
            close_price = round(close_price / self.tick_size) * self.tick_size

            # Ensure H >= O,C and L <= O,C
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)

            # Volume: higher during transitions, lower during balance
            if balance:
                volume = random.gauss(500, 150)
            else:
                volume = random.gauss(800, 300)
            volume = max(100, volume)

            # Delta: proportional to direction
            direction = 1 if close_price > open_price else -1
            delta = direction * volume * random.uniform(0.3, 0.7)

            self._candles.append(GeneratedCandle(
                time=time_str,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=round(volume),
                delta=round(delta),
            ))

            price = close_price

    def _generate_failed_breakout(
        self, start: int, end: int, base: float, vah: float, val: float
    ) -> None:
        """Generate a failed breakout pattern.

        Price breaks above VAH, fails, and snaps back inside.
        """
        price = self._candles[-1].close if self._candles else base
        mid = (start + end) // 2

        for minute in range(start, end):
            hour = 9 + minute // 60
           min_val = minute % 60
            time_str = f"{self.date}T{hour:02d}:{min:02d}:00"

            if minute < mid:
                # Breakout attempt
                price += random.uniform(2, 8)
                volume = random.gauss(1200, 300)
                delta = abs(volume) * random.uniform(0.5, 0.8)
            else:
                # Snap back
                price -= random.uniform(5, 15)
                volume = random.gauss(1000, 250)
                delta = -abs(volume) * random.uniform(0.4, 0.7)

            open_price = price - random.uniform(0, 3)
            close_price = price
            high_price = max(open_price, close_price) + random.uniform(0, 5)
            low_price = min(open_price, close_price) - random.uniform(0, 5)

            # Round
            open_price = round(open_price / self.tick_size) * self.tick_size
            high_price = round(max(high_price, open_price, close_price) / self.tick_size) * self.tick_size
            low_price = round(min(low_price, open_price, close_price) / self.tick_size) * self.tick_size
            close_price = round(close_price / self.tick_size) * self.tick_size

            self._candles.append(GeneratedCandle(
                time=time_str,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=round(max(100, volume)),
                delta=round(delta),
            ))

    def _generate_imbalanced_breakout(
        self, name: str, start: int, end: int,
        base: float, vah: float, val: float,
        direction: str,
    ) -> None:
        """Generate an imbalanced breakout with displacement and acceptance."""
        price = self._candles[-1].close if self._candles else base
        trend_strength = 3 if direction == "UP" else -3

        for minute in range(start, end):
            hour = 9 + minute // 60
           min_val = minute % 60
            time_str = f"{self.date}T{hour:02d}:{min:02d}:00"

            # Strong directional move
            price += trend_strength + random.gauss(0, 2)
            volume = random.gauss(1500, 400)  # High volume breakout
            delta = trend_strength * volume * 0.6

            open_price = price - trend_strength * 0.5
            close_price = price
            high_price = max(open_price, close_price) + abs(random.gauss(0, 3))
            low_price = min(open_price, close_price) - abs(random.gauss(0, 1))

            # Round
            open_price = round(open_price / self.tick_size) * self.tick_size
            high_price = round(max(high_price, open_price, close_price) / self.tick_size) * self.tick_size
            low_price = round(min(low_price, open_price, close_price) / self.tick_size) * self.tick_size
            close_price = round(close_price / self.tick_size) * self.tick_size

            self._candles.append(GeneratedCandle(
                time=time_str,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=round(max(200, volume)),
                delta=round(delta),
            ))

    def save(self, filepath: str) -> None:
        """Save generated candles to JSON."""
        data = {
            "symbol": self.symbol,
            "date": self.date,
            "base_price": self.base_price,
            "tick_size": self.tick_size,
            "candles": [
                {
                    "time": c.time,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "delta": c.delta,
                }
                for c in self._candles
            ],
        }
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved {len(self._candles)} candles to {filepath}")

    @property
    def candles(self) -> list[GeneratedCandle]:
        return list(self._candles)


def generate_all_samples(output_dir: str = "appv2/sample_data") -> None:
    """Generate all sample data files."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # NIFTY balanced day
    gen = SampleDataGenerator(
        symbol="NIFTY", base_price=23400.0, tick_size=0.05,
    )
    gen.generate_balanced_day()
    gen.save(f"{output_dir}/nifty_balanced.json")

    # NIFTY imbalanced day
    gen = SampleDataGenerator(
        symbol="NIFTY", base_price=23400.0, tick_size=0.05,
    )
    gen.generate_imbalanced_day()
    gen.save(f"{output_dir}/nifty_imbalanced.json")

    # CRUDEOIL balanced day
    gen = SampleDataGenerator(
        symbol="CRUDEOIL", base_price=6800.0, tick_size=1.0,
    )
    gen.generate_balanced_day()
    gen.save(f"{output_dir}/crudeoil_balanced.json")

    # CRUDEOIL imbalanced day
    gen = SampleDataGenerator(
        symbol="CRUDEOIL", base_price=6800.0, tick_size=1.0,
    )
    gen.generate_imbalanced_day()
    gen.save(f"{output_dir}/crudeoil_imbalanced.json")

    print(f"\nGenerated 4 sample data files in {output_dir}/")


if __name__ == "__main__":
    generate_all_samples()
