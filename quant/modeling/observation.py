"""Identity of the market observation used to produce a forecast."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForecastObservationIdentity:
    symbol: str
    source_symbol: str
    timeframe_seconds: int
    observed_at: str
    bar_index: int
    close: float
    is_complete: bool
    synthetic_padding_count: int = 0
