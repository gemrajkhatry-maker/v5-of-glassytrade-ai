"""Signal Validator — validates signals before execution.

Provides staleness checks, direction validation, and risk validation
to prevent executing stale or invalid signals.

Usage:
    validator = SignalValidator()
    if validator.validate_staleness(signal, current_tick):
        # Signal is fresh, safe to execute
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.constants import (
    SIGNAL_TTL_SECONDS,
    VWAP_EXTREME_MULTIPLIER,
)

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Signal
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


class SignalValidator:
    """Validates signals before execution."""

    @staticmethod
    def validate_staleness(
        signal: Signal,
        current_tick: OHLC,
        max_age_seconds: int = SIGNAL_TTL_SECONDS,
    ) -> bool:
        """Check if signal is stale (too old to execute).

        Args:
            signal: The signal to validate.
            current_tick: Current market tick.
            max_age_seconds: Maximum age in seconds (default: 600s = 10min).

        Returns:
            True if signal is fresh, False if stale.
        """
        if not hasattr(signal, "timestamp") or not signal.timestamp:
            return True  # No timestamp = assume fresh

        try:
            # Parse signal timestamp
            sig_time_str = str(signal.timestamp).replace("Z", "+00:00")
            sig_time = datetime.fromisoformat(sig_time_str)

            # Parse current tick time
            tick_time_str = str(current_tick.time).replace("Z", "+00:00")
            tick_time = datetime.fromisoformat(tick_time_str)

            # Ensure both have timezone info
            if sig_time.tzinfo is None:
                sig_time = sig_time.replace(tzinfo=timezone.utc)
            if tick_time.tzinfo is None:
                tick_time = tick_time.replace(tzinfo=timezone.utc)

            age_seconds = (tick_time - sig_time).total_seconds()

            if age_seconds > max_age_seconds:
                logger.warning(
                    "Signal stale: age=%.0fs > max=%ds",
                    age_seconds,
                    max_age_seconds,
                )
                return False

            return True

        except (ValueError, TypeError, OSError) as e:
            logger.debug("Signal timestamp parse failed: %s — assuming fresh", e)
            return True  # Parse failure = assume fresh

    @staticmethod
    def validate_direction(
        signal: Signal,
        agent_direction: str,
    ) -> bool:
        """Check if signal direction matches agent decision.

        Args:
            signal: The signal to validate.
            agent_direction: Agent's direction (LONG, SHORT, FLAT).

        Returns:
            True if directions match or agent is FLAT.
        """
        signal_direction = "LONG" if signal.is_buy else "SHORT"

        if agent_direction == "FLAT":
            return True  # Agent has no opinion — trust signal

        if agent_direction != signal_direction:
            logger.info(
                "Direction mismatch: signal=%s, agent=%s",
                signal_direction,
                agent_direction,
            )
            return False

        return True

    @staticmethod
    def validate_vwap_extreme(
        signal: Signal,
        vwap_upper_2: float,
        vwap_lower_2: float,
    ) -> bool:
        """Check if signal is at VWAP extreme (beyond 2σ).

        Args:
            signal: The signal to validate.
            vwap_upper_2: Upper 2σ VWAP band.
            vwap_lower_2: Lower 2σ VWAP band.

        Returns:
            True if not at extreme, False if at extreme.
        """
        if vwap_upper_2 <= 0 or vwap_lower_2 <= 0:
            return True  # No VWAP data = assume OK

        price = float(signal.price)

        if signal.is_buy and price >= vwap_upper_2 * VWAP_EXTREME_MULTIPLIER:
            logger.info(
                "VWAP extreme: LONG at >+2σ (price=%.2f, band=%.2f)",
                price,
                vwap_upper_2,
            )
            return False

        if not signal.is_buy and price <= vwap_lower_2 * VWAP_EXTREME_MULTIPLIER:
            logger.info(
                "VWAP extreme: SHORT at <-2σ (price=%.2f, band=%.2f)",
                price,
                vwap_lower_2,
            )
            return False

        return True

    @staticmethod
    def validate_all(
        signal: Signal,
        current_tick: OHLC,
        agent_direction: str = "FLAT",
        vwap_upper_2: float = 0.0,
        vwap_lower_2: float = 0.0,
    ) -> tuple[bool, str]:
        """Run all validations and return (passed, reason).

        Args:
            signal: The signal to validate.
            current_tick: Current market tick.
            agent_direction: Agent's direction.
            vwap_upper_2: Upper 2σ VWAP band.
            vwap_lower_2: Lower 2σ VWAP band.

        Returns:
            Tuple of (passed: bool, reason: str).
        """
        if not SignalValidator.validate_staleness(signal, current_tick):
            return False, "SIGNAL_STALE"

        if not SignalValidator.validate_direction(signal, agent_direction):
            return False, "DIRECTION_MISMATCH"

        if not SignalValidator.validate_vwap_extreme(
            signal, vwap_upper_2, vwap_lower_2
        ):
            return False, "VWAP_EXTREME"

        return True, "ALL_VALID"