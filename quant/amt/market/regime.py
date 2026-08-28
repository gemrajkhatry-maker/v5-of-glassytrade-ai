"""Regime Detector — Fabio Rule 8 contraction + squeeze detection.

Provides contraction detection (after expansion, the range compresses below a
threshold of the expansion range) and the squeeze setup (trapped participants
forced to cover = entry catalyst). ``detect_squeeze`` is consumed by the AMT
analyzer; everything else that lived here (LLM-trigger detection, failed-entry
re-entry blocking, second-drive tracking, Bollinger/ATR squeeze variants,
follow-through analysis) had no production callers and was removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from quant.contracts.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SqueezeSignal:
    """Squeeze setup: trapped participants + recovery = entry catalyst."""

    direction: str  # "LONG" or "SHORT"
    trapped_level: float
    recovery_price: float


@dataclass
class ContractionConfig:
    """Tunable thresholds for contraction detection (Fabio Rule 8)."""

    contraction_ratio: float = (
        0.30  # current range < ratio * expansion range => contracting
    )
    lookback: int = 20  # candles to measure current range


class RegimeDetector:
    """Contraction detection (Fabio Rule 8) + squeeze setup detection."""

    def __init__(self, contraction_config: ContractionConfig | None = None) -> None:
        self._config = contraction_config or ContractionConfig()

    # ------------------------------------------------------------------
    # Fabio Rule 8 — Contraction Detection
    # ------------------------------------------------------------------

    def is_contracting(self, data: list[OHLC], lookback: int = 20) -> bool:
        """Detect contraction after expansion.

        Compares the range of the last *lookback* candles against the
        range of the preceding *lookback* candles (the expansion window).
        If the current range is less than ``contraction_ratio`` (default
        30%) of the expansion range, the market is contracting.

        When contracting, no new trend trades should be taken — only
        mean-reversion setups are valid.
        """
        if len(data) < lookback * 2:
            return False

        # Expansion window: candles before the current lookback window
        expansion_window = data[-(lookback * 2) : -lookback]
        exp_high = max(c.high for c in expansion_window)
        exp_low = min(c.low for c in expansion_window)
        expansion_range = exp_high - exp_low

        if expansion_range <= 0:
            return False

        # Current window
        current_window = data[-lookback:]
        cur_high = max(c.high for c in current_window)
        cur_low = min(c.low for c in current_window)
        current_range = cur_high - cur_low

        ratio = current_range / expansion_range
        is_contracted = ratio < self._config.contraction_ratio

        if is_contracted:
            logger.debug(
                "Contraction detected: range=%.2f expansion=%.2f ratio=%.2f%%",
                current_range,
                expansion_range,
                ratio * 100,
            )

        return is_contracted

    # ------------------------------------------------------------------
    # Squeeze setup (Fabio's primary live setup)
    # ------------------------------------------------------------------

    def detect_squeeze(self, data: list, amt_result) -> SqueezeSignal | None:
        """Detect squeeze: contraction + failed level recovery.

        Fabio's primary live setup: trapped participants forced to cover = entry fuel.
        """
        if len(data) < 20:
            return None

        if not self.is_contracting(data):
            return None

        val = amt_result.value_area_low
        vah = amt_result.value_area_high

        if val <= 0 or vah <= 0:
            return None

        recent = data[-5:]
        current_price = data[-1].close

        # Long squeeze: price broke below VAL then recovered above it
        broke_low = any(c.low < val for c in recent)
        recovered_above = current_price > val
        if broke_low and recovered_above:
            return SqueezeSignal(
                direction="LONG", trapped_level=val, recovery_price=current_price
            )

        # Short squeeze: price broke above VAH then recovered below it
        broke_high = any(c.high > vah for c in recent)
        recovered_below = current_price < vah
        if broke_high and recovered_below:
            return SqueezeSignal(
                direction="SHORT", trapped_level=vah, recovery_price=current_price
            )

        return None
