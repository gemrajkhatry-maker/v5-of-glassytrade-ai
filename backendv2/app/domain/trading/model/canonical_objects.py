"""Canonical value objects passed through the pipeline.

These are the single source of truth for key domain concepts:
- TradingSignal: all signal metadata in one immutable object
- VWAPProfile: VWAP price + sigma bands with query methods
- TickContext: accumulates state as a tick flows through the pipeline

Adding a field here propagates it to all consumers automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VWAPBias(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"
    AT = "AT"


class SetupType(str, Enum):
    AAA = "AAA"
    VA_FADE = "VA_FADE"
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"


@dataclass(frozen=True)
class VWAPBand:
    """A single sigma band around VWAP price."""
    sigma: int
    upper: float
    lower: float


@dataclass(frozen=True)
class VWAPProfile:
    """VWAP price with sigma bands and bias query methods.

    This is the canonical representation of VWAP. All consumers should use
    this object instead of raw `vwap`, `vwap_upper_1`, `vwap_lower_1` fields.
    """

    price: float
    bands: tuple[VWAPBand, ...]
    bias: VWAPBias = VWAPBias.AT

    def band(self, sigma: int) -> VWAPBand | None:
        """Return the VWAPBand with the given sigma, or None if not present."""
        for b in self.bands:
            if b.sigma == sigma:
                return b
        return None

    def is_price_above(self, sigma: int) -> bool:
        """Return True if price is above the upper band of given sigma."""
        b = self.band(sigma)
        return b is not None and self.price > b.upper

    def is_price_below(self, sigma: int) -> bool:
        """Return True if price is below the lower band of given sigma."""
        b = self.band(sigma)
        return b is not None and self.price < b.lower

    def distance_from_band(self, sigma: int) -> float:
        """Return distance from the nearest edge of the given sigma band."""
        b = self.band(sigma)
        if b is None:
            return 0.0
        if self.price > b.upper:
            return self.price - b.upper
        if self.price < b.lower:
            return b.lower - self.price
        return 0.0


@dataclass(frozen=True)
class TradingSignal:
    """Canonical signal object passed through all pipeline stages.

    Every pipeline stage, handler, and schema reads from this object.
    No stage re-derives signal data from raw inputs.
    """

    symbol: str

    # Core signal
    direction: SignalDirection = SignalDirection.NEUTRAL
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    grade: int = 0  # 0-10 composite grade
    aggression_score: float = 0.0  # 0.0-5.0

    # Session context
    session_phase: str = "UNKNOWN"
    vwap_bias: VWAPBias = VWAPBias.AT

    # Price levels
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    # Setup classification
    setup_type: SetupType = SetupType.AAA

    # Microstructure
    absorption_strength: float = 0.0
    footprint_alignment: str = ""
    risk_reward_ratio: float = 0.0

    # Order flow
    ofi: float = 0.0

    # Metadata
    timestamp: datetime | None = field(default=None, compare=False)
    source: str = field(default="pipeline", compare=False)
    reason: str = field(default="", compare=False)
    metadata: dict[str, Any] | None = field(default=None, compare=False)

    def is_valid(self) -> bool:
        """Check if signal meets minimum viability criteria."""
        return (
            self.direction != SignalDirection.NEUTRAL
            and self.grade >= 5
            and self.risk_reward_ratio >= 1.5
            and self.entry_price > 0
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON / event bus transport."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "confidence": self.confidence.value,
            "grade": self.grade,
            "aggression_score": self.aggression_score,
            "session_phase": self.session_phase,
            "vwap_bias": self.vwap_bias.value,
            "entry": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "setup_type": self.setup_type.value,
            "absorption_strength": self.absorption_strength,
            "footprint_alignment": self.footprint_alignment,
            "risk_reward_ratio": self.risk_reward_ratio,
            "ofi": self.ofi,
            "source": self.source,
            "reason": self.reason,
        }

    @classmethod
    def from_amt_result(cls, symbol: str, amt_result: dict[str, Any]) -> TradingSignal:
        """Build signal from AMT analyzer result dict."""
        return cls(
            symbol=symbol,
            direction=SignalDirection(amt_result.get("direction", "NEUTRAL")),
            confidence=ConfidenceLevel(amt_result.get("confidence", "LOW")),
            grade=int(amt_result.get("grade", 0) or 0),
            aggression_score=float(amt_result.get("aggression_score", 0.0) or 0.0),
            session_phase=str(amt_result.get("session_phase", "UNKNOWN")),
            vwap_bias=VWAPBias(amt_result.get("vwap_bias", "AT")),
            entry_price=float(amt_result.get("entry_price", 0.0) or 0.0),
            stop_loss=float(amt_result.get("stop_loss", 0.0) or 0.0),
            take_profit=float(amt_result.get("take_profit", 0.0) or 0.0),
            setup_type=SetupType(amt_result.get("setup_type", "AAA")),
            absorption_strength=float(amt_result.get("absorption_strength", 0.0) or 0.0),
            footprint_alignment=str(amt_result.get("footprint_alignment", "")),
            risk_reward_ratio=float(amt_result.get("risk_reward_ratio", 0.0) or 0.0),
            ofi=float(amt_result.get("ofi", 0.0) or 0.0),
            source=str(amt_result.get("source", "pipeline")),
            reason=str(amt_result.get("reason", "")),
        )