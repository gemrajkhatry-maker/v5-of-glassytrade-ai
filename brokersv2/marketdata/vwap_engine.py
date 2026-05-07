"""Real-time VWAP calculation engine with session and anchored support."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

from brokersv2.domain.market.events import TickEvent


class VWAPTimeframe(Enum):
    """VWAP calculation timeframes."""
    DAILY = "DAILY"
    SESSION = "SESSION"
    CUSTOM = "CUSTOM"


class VWAPError(Exception):
    """Base exception for VWAP engine errors."""
    pass


@dataclass(frozen=True)
class VWAPResult:
    """VWAP calculation result."""
    security_id: str
    symbol: str
    timestamp: datetime
    vwap: Decimal
    cumulative_volume: int
    cumulative_turnover: Decimal
    current_price: Optional[Decimal] = None

    @property
    def vwap_deviation_pct(self) -> Optional[float]:
        """Calculate deviation from VWAP as percentage."""
        if self.current_price and self.vwap != 0:
            return float((self.current_price - self.vwap) / self.vwap * 100)
        return None


@dataclass
class AnchoredVWAP:
    """VWAP anchored to specific price/time level."""
    anchor_price: Decimal
    anchor_time: datetime
    vwap_at_anchor: Decimal
    anchor_volume: int

    @classmethod
    def from_calculator(cls, calc: "VWAPCalculator", anchor_price: Decimal, anchor_time: datetime) -> "AnchoredVWAP":
        """Create anchored VWAP from calculator state."""
        return cls(
            anchor_price=anchor_price,
            anchor_time=anchor_time,
            vwap_at_anchor=calc.current_vwap or Decimal("0"),
            anchor_volume=calc.current_volume,
        )

    def deviation_from_anchor(self, current_vwap: Decimal) -> float:
        """Calculate deviation from anchored VWAP."""
        if self.vwap_at_anchor != 0:
            return float((current_vwap - self.vwap_at_anchor) / self.vwap_at_anchor * 100)
        return 0.0


@dataclass
class VWAPSession:
    """VWAP session with start/end times."""
    security_id: str
    start_time: datetime
    end_time: datetime
    auto_reset: bool = False

    def __post_init__(self):
        self._calculator = VWAPCalculator(security_id=self.security_id)

    def process_tick(self, tick: TickEvent) -> Optional[VWAPResult]:
        """Process tick and return VWAP result."""
        # Auto-reset if session expired
        if self.auto_reset and self.is_expired(tick.timestamp):
            self._calculator.reset()

        return self._calculator.process_tick(tick)

    def get_result(self) -> Optional[VWAPResult]:
        """Get current VWAP result."""
        return self._calculator.get_current_vwap()

    def is_expired(self, current_time: datetime) -> bool:
        """Check if session has expired."""
        return current_time > self.end_time

    def reset(self):
        """Reset session VWAP."""
        self._calculator.reset()


@dataclass
class VWAPCalculator:
    """
    Real-time VWAP calculator.
    
    VWAP = Σ(Typical Price × Volume) / Σ(Volume)
    where Typical Price = (High + Low + Close) / 3
    
    Features:
    - Cumulative VWAP calculation
    - Session management
    - Anchored VWAP support
    - Multiple timeframe support
    """

    security_id: str
    timeframe: VWAPTimeframe = VWAPTimeframe.DAILY
    session_start: Optional[datetime] = None
    window_minutes: Optional[int] = None

    def __post_init__(self):
        self._cumulative_volume: int = 0
        self._cumulative_turnover: Decimal = Decimal("0")
        self._current_vwap: Optional[Decimal] = None
        self._last_timestamp: Optional[datetime] = None
        self._tick_history: list[TickEvent] = []

    def process_tick(self, tick: TickEvent) -> Optional[VWAPResult]:
        """
        Process a tick and update VWAP calculation.
        
        Returns VWAPResult if successful.
        Raises VWAPError if security_id mismatch.
        """
        # Validate security ID
        if tick.security_id != self.security_id:
            raise VWAPError(
                f"security_id mismatch: expected {self.security_id}, "
                f"got {tick.security_id}"
            )

        # Handle timeframe-specific logic
        if self.timeframe == VWAPTimeframe.CUSTOM and self.window_minutes:
            self._apply_window(tick)

        # Calculate typical price: (high + low + close) / 3
        typical_price = (tick.high + tick.low + tick.close) / Decimal("3")

        # Update cumulative values
        volume = tick.volume
        turnover = typical_price * volume

        self._cumulative_volume += volume
        self._cumulative_turnover += turnover

        # Calculate VWAP
        if self._cumulative_volume > 0:
            self._current_vwap = self._cumulative_turnover / self._cumulative_volume

        self._last_timestamp = tick.timestamp

        # Store tick for window management
        if self.timeframe == VWAPTimeframe.CUSTOM:
            self._tick_history.append(tick)

        # Return result
        return VWAPResult(
            security_id=tick.security_id,
            symbol=tick.symbol,
            timestamp=tick.timestamp,
            vwap=self._current_vwap or Decimal("0"),
            cumulative_volume=self._cumulative_volume,
            cumulative_turnover=self._cumulative_turnover,
            current_price=tick.ltp,
        )

    def get_current_vwap(self) -> Optional[VWAPResult]:
        """Get current VWAP without processing new tick."""
        if self._current_vwap is None:
            return None

        return VWAPResult(
            security_id=self.security_id,
            symbol="",
            timestamp=self._last_timestamp or datetime.now(),
            vwap=self._current_vwap,
            cumulative_volume=self._cumulative_volume,
            cumulative_turnover=self._cumulative_turnover,
        )

    def reset(self):
        """Reset VWAP calculation."""
        self._cumulative_volume = 0
        self._cumulative_turnover = Decimal("0")
        self._current_vwap = None
        self._last_timestamp = None
        self._tick_history.clear()

    @property
    def current_volume(self) -> int:
        """Get current cumulative volume."""
        return self._cumulative_volume

    @property
    def current_turnover(self) -> Decimal:
        """Get current cumulative turnover."""
        return self._cumulative_turnover

    @property
    def current_vwap(self) -> Optional[Decimal]:
        """Get current VWAP value."""
        return self._current_vwap

    def _apply_window(self, tick: TickEvent):
        """Apply sliding window for custom timeframe."""
        if not self.window_minutes or not self._last_timestamp:
            return

        window = timedelta(minutes=self.window_minutes)
        cutoff = tick.timestamp - window

        # Remove old ticks and recalculate
        self._tick_history = [
            t for t in self._tick_history
            if t.timestamp >= cutoff
        ]

        # Recalculate from scratch
        self._cumulative_volume = 0
        self._cumulative_turnover = Decimal("0")

        for t in self._tick_history:
            typical_price = (t.high + t.low + t.close) / Decimal("3")
            self._cumulative_volume += t.volume
            self._cumulative_turnover += typical_price * t.volume

        if self._cumulative_volume > 0:
            self._current_vwap = self._cumulative_turnover / self._cumulative_volume
