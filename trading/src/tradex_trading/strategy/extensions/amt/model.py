"""Greenfield AMT value objects used by the v4 strategy extension."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from tradex_domain.instruments import Instrument


class AMTPhase(StrEnum):
    WAITING = "WAITING"
    ABSORBING = "ABSORBING"
    ACCUMULATING = "ACCUMULATING"
    AGGRESSION = "AGGRESSION"


@dataclass(frozen=True, slots=True)
class AMTSnapshot:
    instrument: Instrument
    timestamp: datetime
    close: Decimal
    poc: Decimal | None
    vah: Decimal | None
    val: Decimal | None
    vwap: Decimal
    upper_1: Decimal
    lower_1: Decimal
    upper_2: Decimal
    lower_2: Decimal
    vwap_std: Decimal
    delta: Decimal
    cvd: Decimal
    cvd_slope: Decimal
    cvd_divergence: str
    absorption_side: str | None
    absorption_strength: Decimal
    absorption_age: int | None
    ib_high: Decimal | None
    ib_low: Decimal | None
    ib_complete: bool
    location: str
    nearest_level: Decimal | None
    profile_shape: str
    lvn_levels: tuple[Decimal, ...]
    hvn_levels: tuple[Decimal, ...]
    phase: AMTPhase = AMTPhase.WAITING
    direction: str | None = None
    book_imbalance: Decimal = Decimal("0")
    book_polr: str = "neutral"
    book_swept_bids: int = 0
    book_swept_asks: int = 0
    absorption_confirmed: bool = False
    aggression_score: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """Compact L2 book signal consumed by the pure kernel at candle close."""

    imbalance_ratio: Decimal = Decimal("0")
    path_of_least_resistance: str = "neutral"
    swept_bids: int = 0
    swept_asks: int = 0


@dataclass(frozen=True, slots=True)
class AMTDecision:
    approved: bool
    setup: str
    direction: str | None
    entry: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    risk_reward: Decimal
    reason: str
    failed_gates: tuple[str, ...] = ()
    cushion: Decimal = Decimal("0")
    pyramid: bool = False


@dataclass(frozen=True, slots=True)
class AMTStrategyConfig:
    ib_bars: int = 6
    value_area_pct: Decimal = Decimal("0.68")
    accumulation_bars: int = 2
    absorption_volume_multiplier: Decimal = Decimal("1.5")
    absorption_range_ratio: Decimal = Decimal("0.5")
    max_absorption_age: int = 5
    vwap_min_width_pct: Decimal = Decimal("0.001")
    vwap_max_width_pct: Decimal = Decimal("0.03")
    minimum_risk_reward: Decimal = Decimal("1.5")
    tick_size: Decimal = Decimal("0.05")
    cvd_slope_window: int = 20
    #: Stop cushioning — stop is placed this many ticks beyond the structural level.
    stop_cushion_ticks: int = 2
    #: Pyramiding — scale into an open position when bar aggression passes the
    #: Fabio threshold (PYRAMID_AGGRESSION_SCORE = 3.0).
    pyramid_enabled: bool = True
    pyramid_aggression_score: Decimal = Decimal("3.0")
    #: Loss cushion — risk shrinks after this many consecutive losses.
    loss_streak_threshold: int = 3
    risk_shrink_factor: Decimal = Decimal("0.5")
