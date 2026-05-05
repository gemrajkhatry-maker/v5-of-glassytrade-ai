"""VWAP service — session-aware VWAP and sigma band calculations."""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class VWAPConfig:
    """Configuration constants for VWAP calculations."""

    MIN_VWAP_STD = 1.0  # Minimum sigma clamp to avoid zero division/noise.
    MAX_VWAP_STD_RATIO = 0.10  # Cap stddev to 10% of VWAP.
    MAX_SIGMA_CLAMP = 4.0  # Clamp extreme sigma values for output stability.
    MAX_SIGMA_WARNING = 10.0  # Log threshold for extreme deviations.


class VWAPState:
    """Mutable VWAP state for one trading session."""

    def __init__(self) -> None:
        self.cum_vol: float = 0.0
        self.cum_quote_vol: float = 0.0
        self.cum_sq_vol: float = 0.0
        self.shift: float = 0.0
        self.price_deviations: deque[float] = deque(maxlen=500)
        self.last_time: str = ""

    def reset(self) -> None:
        self.cum_vol = 0.0
        self.cum_quote_vol = 0.0
        self.cum_sq_vol = 0.0
        self.shift = 0.0
        self.price_deviations.clear()
        self.last_time = ""


class VWAPResult:
    """Computed VWAP bands + deviation metadata."""

    def __init__(
        self,
        session_vwap: float,
        vwap_upper_1: float,
        vwap_lower_1: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
        vwap_std: float,
        vwap_deviation_sigmas: float | None,
    ) -> None:
        self.session_vwap = session_vwap
        self.vwap_upper_1 = vwap_upper_1
        self.vwap_lower_1 = vwap_lower_1
        self.vwap_upper_2 = vwap_upper_2
        self.vwap_lower_2 = vwap_lower_2
        self.vwap_std = vwap_std
        self.vwap_deviation_sigmas = vwap_deviation_sigmas


class VWAPService:
    """Stateful VWAP calculator.

    Keeps session state so subsequent updates are incremental.
    """

    def __init__(self, config: VWAPConfig | None = None) -> None:
        self.config = config or VWAPConfig()
        self._state = VWAPState()

    def update(self, typical_price: float, volume: float, time: str) -> float:
        """Update VWAP with a new market sample.

        Args:
            typical_price: Typical price, usually (high + low + close) / 3.
            volume: Trade/aggregate candle volume.
            time: Timestamp string; any ISO-like string is accepted.
        """
        tp = float(typical_price)
        vol = float(volume)
        quote_vol = tp * vol if vol > 0 else 0.0

        if self._should_reset_session(time):
            self._state.reset()

        self._state.last_time = str(time)
        self._state.cum_vol += vol
        self._state.cum_quote_vol += quote_vol

        if self._state.shift == 0.0:
            self._state.shift = tp

        shifted = tp - self._state.shift
        self._state.cum_sq_vol += shifted * shifted * vol
        self._state.price_deviations.append(shifted)

        return self.get_vwap()

    def _extract_date(self, time: str) -> str:
        """Extract YYYY-MM-DD or fallback full string."""
        if not isinstance(time, str):
            return str(time)
        if len(time) >= 10:
            return time[:10]
        return time

    def _should_reset_session(self, time: str) -> bool:
        """Reset if date has changed or stream moved backwards."""
        if not self._state.last_time:
            return False
        try:
            current = self._extract_date(str(time))
            previous = self._extract_date(self._state.last_time)
            if current != previous:
                return True
            return str(time) < self._state.last_time
        except Exception:
            return False

    def get_vwap(self) -> float:
        """Return current session VWAP."""
        if self._state.cum_vol > 0:
            return self._state.cum_quote_vol / self._state.cum_vol
        return 0.0

    def build_bands(self, live_price: float, session_vwap: float = 0.0) -> VWAPResult:
        """Build VWAP mean/band levels from current session state."""
        if session_vwap == 0.0:
            session_vwap = self.get_vwap()

        vwap_std = self._calculate_std()
        vwap_std = self._clamp_std(vwap_std, session_vwap)

        vwap_upper_1 = session_vwap + vwap_std
        vwap_lower_1 = session_vwap - vwap_std
        vwap_upper_2 = session_vwap + (2 * vwap_std)
        vwap_lower_2 = session_vwap - (2 * vwap_std)

        vwap_deviation_sigmas = self._calculate_deviation_sigmas(
            float(live_price), session_vwap, vwap_std
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
        if self._state.cum_vol <= 0 or len(self._state.price_deviations) <= 1:
            return 0.0
        deviations = list(self._state.price_deviations)
        mean = sum(deviations) / len(deviations)
        variance = sum((d - mean) ** 2 for d in deviations) / len(deviations)
        return math.sqrt(max(0.0, variance))

    def _clamp_std(self, std: float, vwap: float) -> float:
        if std < self.config.MIN_VWAP_STD:
            logger.debug("VWAP std clamped to minimum %.2f", self.config.MIN_VWAP_STD)
            return self.config.MIN_VWAP_STD

        max_std = vwap * self.config.MAX_VWAP_STD_RATIO
        if std > max_std:
            logger.warning(
                "VWAP std clamped from %.2f to %.2f (max 10%% of VWAP=%.2f)",
                std,
                max_std,
                vwap,
            )
            return max_std

        return std

    def _calculate_deviation_sigmas(
        self, live_price: float, vwap: float, std: float
    ) -> float | None:
        if std <= 0:
            return None

        sigma = (live_price - vwap) / std
        if abs(sigma) > self.config.MAX_SIGMA_CLAMP:
            logger.warning(
                "VWAP deviation clamped %.2fσ -> ±%.1fσ (vwap=%.2f, live=%.2f, std=%.2f)",
                sigma,
                self.config.MAX_SIGMA_CLAMP,
                vwap,
                live_price,
                std,
            )
            return math.copysign(self.config.MAX_SIGMA_CLAMP, sigma)

        if abs(sigma) > self.config.MAX_SIGMA_WARNING:
            logger.warning(
                "VWAP deviation extreme %.2fσ (vwap=%.2f, live=%.2f, std=%.2f)",
                sigma,
                vwap,
                live_price,
                std,
            )

        return sigma

    def reset(self) -> None:
        """Clear session state."""
        self._state.reset()
