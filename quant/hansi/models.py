"""HARSI (Heikin-Ashi RSI Oscillator) domain types.

Pure, deterministic domain types — no I/O, no imports from backend/,
no external dependencies. Mirrors the Pine Script / TypeScript types
in frontend/components/chart/HARSIManager.ts for cross-parity.

jayrogers: https://www.tradingview.com/script/1o4oWbEx-Heikin-Ashi-RSI-Oscillator/
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Zone(str, Enum):
    """RSI zone classification based on zero-median RSI value."""
    EXTENDED_OB = "EXTENDED_OB"   # rsi >= +30
    OVERBOUGHT = "OVERBOUGHT"     # +20 <= rsi < +30
    NEUTRAL = "NEUTRAL"           # -20 < rsi < +20
    OVERSOLD = "OVERSOLD"         # -30 < rsi <= -20
    EXTENDED_OS = "EXTENDED_OS"   # rsi <= -30


class Bias(str, Enum):
    """Trend bias from HA candle color + RSI side of zero."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Crossover(str, Enum):
    """Crossover state vs previous bar."""
    CROSS_UP = "CROSS_UP"
    CROSS_DOWN = "CROSS_DOWN"
    NO_CROSS = "NO_CROSS"


class Signal(str, Enum):
    """Trade signal derived from crossover + zone + bias."""
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


class Direction(str, Enum):
    """Position direction."""
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HARSICandle:
    """A single HARSI Heikin-Ashi candle.

    Time is an IST timestamp string (ISO 8601 or Unix seconds as str),
    matching the OHLCData.time convention used across the codebase.
    """
    time: str
    open: float
    high: float
    low: float
    close: float
    color: str              # "green" | "red"


@dataclass(frozen=True)
class ReferenceLevels:
    """Fixed reference levels for the HARSI oscillator panel."""
    ob: float = 20.0
    ob_extreme: float = 30.0
    median: float = 0.0
    os: float = -20.0
    os_extreme: float = -30.0


@dataclass(frozen=True)
class HARSISignal:
    """Complete HARSI signal for the most recent bar.

    This is the domain object produced by HARSIComputer.compute().
    It is pure (frozen dataclass, no side effects) and serializable
    (all fields are JSON-primitive or nested frozen dataclass).
    """
    time: str
    ha_candle: HARSICandle
    rsi_value: float
    rsi_histogram: float            # same as rsi_value (for histogram display)
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    zone: Zone
    bias: Bias
    crossover: Crossover
    signal: Signal
    reference_levels: ReferenceLevels = ReferenceLevels()
    warmup: bool = False
    # For extreme-only filter logic — populated by the computer.
    prev_zone: Optional[Zone] = None
    prev_ha_close: Optional[float] = None


@dataclass(frozen=True)
class GateResult:
    """A single risk-gate evaluation result."""
    gate: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class HARSIDecision:
    """Strategy decision output for one bar evaluation."""
    direction: Direction
    signal_type: str                 # "HARSI_CROSS_UP" | "HARSI_CROSS_DOWN" | "FLAT_NO_SIGNAL" | "FLAT_GATE_BLOCKED"
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    rr_ratio: Optional[float] = None
    model_label: str                # "HARSI_BULL" | "HARSI_BEAR" | "HARSI_NEUTRAL" | "HARSI_REVERSAL"
    reason: str
    gate_results: list[GateResult] = ()
