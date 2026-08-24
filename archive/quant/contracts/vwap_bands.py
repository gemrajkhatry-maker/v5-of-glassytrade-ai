"""VWAP Bands value object.

Encapsulates session VWAP and deviation bands. Extracted from the flat
AMTResult dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VWAPBands:
    """Session VWap and standard deviation bands.

    Attributes:
        vwap: Rolling session VWAP.
        upper_1: VWAP + 1 standard deviation.
        lower_1: VWAP - 1 standard deviation.
        upper_2: VWAP + 2 standard deviations.
        lower_2: VWAP - 2 standard deviations.
        deviation_sigmas: Current price deviation in sigma units.
    """

    vwap: float = 0.0
    upper_1: float = 0.0
    lower_1: float = 0.0
    upper_2: float = 0.0
    lower_2: float = 0.0
    deviation_sigmas: float | None = None

    @property
    def has_data(self) -> bool:
        """Whether VWAP bands have meaningful data."""
        return self.vwap > 0.0
