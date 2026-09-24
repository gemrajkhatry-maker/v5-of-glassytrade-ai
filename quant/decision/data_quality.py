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


def normalize_data_quality(value) -> DataQuality:
    try:
        return value if isinstance(value, DataQuality) else DataQuality(str(value).upper())
    except (TypeError, ValueError):
        return DataQuality.UNAVAILABLE


def normalize_evidence_provenance(value) -> dict[str, DataQuality]:
    """Normalize each decision-critical family; missing families fail closed."""
    value = value if isinstance(value, dict) else {}
    return {
        family: normalize_data_quality(value.get(family))
        for family in REQUIRED_EVIDENCE_FAMILIES
    }


def failed_evidence_families(value, *, allow_proxy_cvd: bool = False) -> tuple[str, ...]:
    provenance = normalize_evidence_provenance(value)
    failed = []
    for family in REQUIRED_EVIDENCE_FAMILIES:
        q = provenance[family]
        if family == "cvd_delta" and allow_proxy_cvd and q in (DataQuality.TICK_EXACT, DataQuality.PRICE_DIRECTION_PROXY):
            continue
        if q is not DataQuality.TICK_EXACT:
            failed.append(family)
    return tuple(failed)


def live_evidence_exact(value, *, allow_proxy_cvd: bool = False) -> bool:
    return not failed_evidence_families(value, allow_proxy_cvd=allow_proxy_cvd)
