"""Opening Range Breakout (ORB) detection.

Implements Fabio's ORB strategy:
- First N bars (default 6) define the opening range
- Breakout above ORB high with volume confirmation → LONG
- Breakdown below ORB low with volume confirmation → SHORT
- False breakout detection (wick breaks but close inside)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ORBResult:
    """Opening Range formation result."""
    orb_high: float = 0.0
    orb_low: float = 0.0
    is_formed: bool = False
    avg_volume: float = 0.0
    bars_count: int = 0


@dataclass(frozen=True)
class ORBBreakoutSignal:
    """ORB breakout signal with entry/stop levels."""
    direction: str = ""  # "LONG" or "SHORT"
    breakout_level: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    confidence: float = 0.0
    is_valid: bool = False
    reason: str = ""


@dataclass
class ORBDetector:
    """Detect Opening Range Breakout setups."""
    
    orb_period: int = 6  # Number of bars to form ORB
    
    def __post_init__(self):
        self._bars: list[dict] = []
        self._orb_range: ORBResult | None = None
    
    def update(self, bar: dict) -> None:
        """Add a bar to ORB formation."""
        if self._orb_range and self._orb_range.is_formed:
            return  # ORB already formed
        
        self._bars.append(bar)
        
        if len(self._bars) >= self.orb_period:
            self._form_orb()
    
    def _form_orb(self) -> None:
        """Calculate ORB high/low from formation period."""
        if len(self._bars) < self.orb_period:
            return
        
        orb_bars = self._bars[:self.orb_period]
        
        orb_high = max(b["high"] for b in orb_bars)
        orb_low = min(b["low"] for b in orb_bars)
        avg_volume = sum(b["volume"] for b in orb_bars) / len(orb_bars)
        
        self._orb_range = ORBResult(
            orb_high=orb_high,
            orb_low=orb_low,
            is_formed=True,
            avg_volume=avg_volume,
            bars_count=self.orb_period,
        )
    
    def get_orb_range(self) -> ORBResult | None:
        """Get current ORB range (None if not formed)."""
        return self._orb_range
    
    def check_breakout(self, bar: dict) -> ORBBreakoutSignal | None:
        """Check if current bar is an ORB breakout."""
        if not self._orb_range or not self._orb_range.is_formed:
            return None
        
        orb_high = self._orb_range.orb_high
        orb_low = self._orb_range.orb_low
        avg_volume = self._orb_range.avg_volume
        
        current_close = bar["close"]
        current_high = bar["high"]
        current_low = bar["low"]
        current_volume = bar["volume"]
        
        # Check volume confirmation (must be above average)
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        if volume_ratio < 1.0:
            return None
        
        # LONG breakout: breaks above ORB high
        if current_high > orb_high:
            # Check if it's a false breakout (close back inside)
            if current_close <= orb_high:
                return ORBBreakoutSignal(
                    direction="LONG",
                    breakout_level=orb_high,
                    is_valid=False,
                    reason="False breakout: close back inside range",
                )
            
            # Valid breakout
            confidence = min(1.0, volume_ratio / 3.0)  # 3x volume = max confidence
            stop_loss = orb_high - (orb_high - orb_low) * 0.5  # 50% of ORB range
            
            return ORBBreakoutSignal(
                direction="LONG",
                breakout_level=orb_high,
                entry_price=current_close,
                stop_loss=stop_loss,
                confidence=confidence,
                is_valid=True,
                reason=f"ORB LONG breakout: {volume_ratio:.1f}x volume",
            )
        
        # SHORT breakdown: breaks below ORB low
        if current_low < orb_low:
            # Check if it's a false breakout (close back inside)
            if current_close >= orb_low:
                return ORBBreakoutSignal(
                    direction="SHORT",
                    breakout_level=orb_low,
                    is_valid=False,
                    reason="False breakdown: close back inside range",
                )
            
            # Valid breakdown
            confidence = min(1.0, volume_ratio / 3.0)
            stop_loss = orb_low + (orb_high - orb_low) * 0.5  # 50% of ORB range
            
            return ORBBreakoutSignal(
                direction="SHORT",
                breakout_level=orb_low,
                entry_price=current_close,
                stop_loss=stop_loss,
                confidence=confidence,
                is_valid=True,
                reason=f"ORB SHORT breakdown: {volume_ratio:.1f}x volume",
            )
        
        return None
    
    def reset(self) -> None:
        """Reset ORB state for new session."""
        self._bars = []
        self._orb_range = None
