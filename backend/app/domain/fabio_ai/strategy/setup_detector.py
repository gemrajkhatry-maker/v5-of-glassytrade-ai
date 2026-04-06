"""Setup Detector — Stub.

Planned feature: AMTSetupDetector for identifying FAILED_AUCTION,
RETURN_TO_VALUE, IMBALANCE_CONTINUATION and other Fabio setups.

Status: Stub — class defined but not fully implemented.
"""

from __future__ import annotations

from typing import Optional
from app.domain.fabio_ai.strategy.protocols import Setup, MarketContext


class AMTSetupDetector:
    """Detect AMT setups from market context.

    Stub implementation — returns None/unknown for all detections
    until the full setup detection logic is implemented.
    """

    def detect(self, context: MarketContext) -> Optional[Setup]:
        """Detect the current AMT setup from market conditions."""
        return None

    def is_failed_auction(self, context: MarketContext) -> bool:
        """Check if market context shows a failed auction pattern."""
        return False

    def is_return_to_value(self, context: MarketContext) -> bool:
        """Check if market context shows return-to-value setup."""
        return False

    def is_imbalance_continuation(self, context: MarketContext) -> bool:
        """Check if market context shows imbalance continuation."""
        return False


def create_setup_detector() -> AMTSetupDetector:
    """Factory for AMT setup detector."""
    return AMTSetupDetector()
