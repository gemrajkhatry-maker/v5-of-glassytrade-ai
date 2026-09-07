"""Canonical market-data provenance used by decision safety gates."""
from enum import Enum


class DataQuality(str, Enum):
    TICK_EXACT = "TICK_EXACT"
    CANDLE_DISTRIBUTED = "CANDLE_DISTRIBUTED"
    CANDLE_GAUSSIAN = "CANDLE_GAUSSIAN"
    PRICE_DIRECTION_PROXY = "PRICE_DIRECTION_PROXY"
    UNAVAILABLE = "UNAVAILABLE"


# High-conviction order-flow entries require exact or distributed evidence.
_ALLOWED_CONVICTION = frozenset({DataQuality.TICK_EXACT, DataQuality.CANDLE_DISTRIBUTED})


def normalize_data_quality(value) -> DataQuality:
    try:
        return value if isinstance(value, DataQuality) else DataQuality(str(value).upper())
    except (TypeError, ValueError):
        return DataQuality.UNAVAILABLE


def conviction_allowed(value) -> bool:
    return normalize_data_quality(value) in _ALLOWED_CONVICTION
