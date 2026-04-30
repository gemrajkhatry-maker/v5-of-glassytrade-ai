"""VWAP Service — VWAP calculation and bands.

Extracted from AMTAnalyzer to follow Single Responsibility Principle.
Handles session VWAP, deviation tracking, and sigma bands.
"""

from __future__ import annotations

import logging
import math
from collections import deque

logger = logging.getLogger(__name__)


class VWAPConfig:
    """Configuration constants for VWAP calculations."""
    
    MIN_VWAP_STD = 1.0  # Minimum std to prevent extreme sigma values
    MAX_VWAP_STD_RATIO = 0.10  # Max 10% of VWAP for std
    MAX_SIGMA_CLAMP = 4.0  # Clamp sigma to ±4 in normal markets
    MAX_SIGMA_WARNING = 10.0  # Warning threshold for extreme deviation


class VWAPState:
    """Mutable VWAP state for session tracking."""
    
    def __init__(self) -> None:
        self.cum_vol: float = 0.0
        self.cum_quote_vol: float = 0.0
        self.cum_sq_vol: float = 0.0  # For variance
        self.shift: float = 0.0  # Reference price for numerically stable variance
        self.price_deviations: deque = deque(maxlen=500)
        self.last_time: str = ""
    
    def reset(self) -> None:
        """Reset state for new session."""
        self.cum_vol = 0.0
        self.cum_quote_vol = 0.0
        self.cum_sq_vol = 0.0
        self.shift = 0.0
        self.price_deviations.clear()
        self.last_time = ""


class VWAPResult:
    """Result of VWAP bands calculation."""
    
    def __init__(
        self,
        session_vwap: float,
        vwap_upper_1: float,
        vwap_lower_1: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
        vwap_std: float,
        vwap_deviation_sigmas: float | None,
    ):
        self.session_vwap = session_vwap
        self.vwap_upper_1 = vwap_upper_1
        self.vwap_lower_1 = vwap_lower_1
        self.vwap_upper_2 = vwap_upper_2
        self.vwap_lower_2 = vwap_lower_2
        self.vwap_std = vwap_std
        self.vwap_deviation_sigmas = vwap_deviation_sigmas


class VWAPService:
    """VWAP calculation service.
    
    Extracted from AMTAnalyzer for single responsibility.
    Handles session VWAP, standard deviation bands, and price deviation tracking.
    """
    
    def __init__(self, config: VWAPConfig | None = None) -> None:
        self.config = config or VWAPConfig()
        self._state = VWAPState()
    
    def update(self, typical_price: float, volume: float, time: str) -> float:
        """Update VWAP with new tick/candle and return current VWAP.
        
        Args:
            typical_price: (high + low + close) / 3
            volume: Volume for this tick/candle
            time: Timestamp in format YYYY-MM-DD HH:MM:SS
            
        Returns:
            Current session VWAP value
        """
        quote_vol = typical_price * volume if volume > 0 else 0.0
        
        # Detect session boundary
        reset_session = self._should_reset_session(time)
        if reset_session:
            self._state.reset()
        
        self._state.last_time = time
        
        # Accumulate for VWAP
        self._state.cum_vol += float(volume)
        self._state.cum_quote_vol += float(quote_vol)
        
        # Shifted variance calculation for numerical stability
        if self._state.shift == 0.0:
            self._state.shift = typical_price
        
        shifted = typical_price - self._state.shift
        self._state.cum_sq_vol += float(shifted * shifted * volume)
        self._state.price_deviations.append(shifted)
        
        return self.get_vwap()
    
    def _should_reset_session(self, time: str) -> bool:
        """Check if new session has started."""
        if not self._state.last_time:
            return False
        
        try:
            # Check date change (first 10 chars: YYYY-MM-DD)
            if len(time) >= 10 and len(self._state.last_time) >= 10:
                if time[:10] != self._state.last_time[:10]:
                    return True
            # Check time running backwards (next day before previous)
            if time < self._state.last_time:
                return True
        except (TypeError, IndexError):
            pass
        
        return False
    
    def get_vwap(self) -> float:
        """Get current VWAP value."""
        if self._state.cum_vol > 0:
            return self._state.cum_quote_vol / self._state.cum_vol
        return 0.0
    
    def build_bands(
        self, live_price: float, session_vwap: float = 0.0
    ) -> VWAPResult:
        """Compute VWAP standard deviation bands (±1σ, ±2σ).
        
        Args:
            live_price: Current price for sigma calculation
            session_vwap: VWAP to use (defaults to current)
            
        Returns:
            VWAPResult with bands and deviation sigmas
        """
        if session_vwap == 0.0:
            session_vwap = self.get_vwap()
        
        vwap_std = self._calculate_std()
        vwap_std = self._clamp_std(vwap_std, session_vwap)
        
        vwap_upper_1 = session_vwap + vwap_std
        vwap_lower_1 = session_vwap - vwap_std
        vwap_upper_2 = session_vwap + 2 * vwap_std
        vwap_lower_2 = session_vwap - 2 * vwap_std
        
        vwap_deviation_sigmas = self._calculate_deviation_sigmas(
            live_price, session_vwap, vwap_std
        )
        
        return VWAPResult(
            session_vwap=session_vwap,
            vwap_upper_1=vwap_upper_1,
            vwap_lower_1=vwap_lower_1,
            vwap_upper_2=vwap_upper_2,
            vwap_lower_2=vwap_lower_2,
            vwap_std=vwap_std,
            vwap_deviation_sigmas=vwap_deviation_sigmas,
        )
    
    def _calculate_std(self) -> float:
        """Calculate VWAP standard deviation from price deviations."""
        if self._state.cum_vol <= 0 or len(self._state.price_deviations) <= 1:
            return 0.0
        
        deviations = list(self._state.price_deviations)
        mean_deviation = sum(deviations) / len(deviations)
        variance = sum((d - mean_deviation) ** 2 for d in deviations) / len(deviations)
        
        return math.sqrt(max(0.0, variance))
    
    def _clamp_std(self, std: float, vwap: float) -> float:
        """Clamp standard deviation to reasonable bounds."""
        # Enforce minimum
        if std < self.config.MIN_VWAP_STD:
            logger.debug("VWAP std clamped to minimum: %.2f", self.config.MIN_VWAP_STD)
            return self.config.MIN_VWAP_STD
        
        # Enforce maximum (10% of VWAP)
        max_std = vwap * self.config.MAX_VWAP_STD_RATIO
        if std > max_std:
            logger.warning(
                "VWAP std clamped from %.2f to %.2f (max 10%% of VWAP=%.2f)",
                std, max_std, vwap
            )
            return max_std
        
        return std
    
    def _calculate_deviation_sigmas(
        self, live_price: float, vwap: float, std: float
    ) -> float | None:
        """Calculate price deviation in standard deviations."""
        if std <= 0:
            return None
        
        sigma = (live_price - vwap) / std
        
        # Clamp extreme values
        if abs(sigma) > self.config.MAX_SIGMA_CLAMP:
            logger.warning(
                "VWAP deviation clamped: %.2fσ → ±%.1fσ (vwap=%.2f, live=%.2f, std=%.2f)",
                sigma, self.config.MAX_SIGMA_CLAMP, vwap, live_price, std
            )
            return math.copysign(self.config.MAX_SIGMA_CLAMP, sigma)
        
        if abs(sigma) > self.config.MAX_SIGMA_WARNING:
            logger.warning(
                "VWAP deviation extreme: %.2fσ — possible data source mismatch "
                "(vwap=%.2f, live=%.2f, std=%.2f)",
                sigma, vwap, live_price, std
            )
        
        return sigma
    
    def reset(self) -> None:
        """Reset VWAP state for new session."""
        self._state.reset()