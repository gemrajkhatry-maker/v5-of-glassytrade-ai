"""Canonical market-data provenance used by decision safety gates."""
from enum import Enum

REQUIRED_EVIDENCE_FAMILIES = (
    "footprint_imbalance",
    "cvd_delta",
    "ofi_depth",
    "absorption",
    "stacked_imbalance",
)


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


def normalize_evidence_provenance(value) -> dict[str, DataQuality]:
    """Normalize each decision-critical family; missing families fail closed."""
    value = value if isinstance(value, dict) else {}
    return {
        family: normalize_data_quality(value.get(family))
        for family in REQUIRED_EVIDENCE_FAMILIES
    }


def live_evidence_exact(value) -> bool:
    return all(
        quality is DataQuality.TICK_EXACT
        for quality in normalize_evidence_provenance(value).values()
    )
