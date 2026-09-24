"""Evidence quality and provenance values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class EvidenceQuality(StrEnum):
    EXACT = "EXACT"
    DERIVED = "DERIVED"
    PROXY = "PROXY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class EvidenceProvenance:
    family: str
    quality: EvidenceQuality
    source: str
    as_of: object | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("family", "source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.quality, EvidenceQuality):
            object.__setattr__(self, "quality", EvidenceQuality(self.quality))
        if self.quality is EvidenceQuality.UNAVAILABLE and not self.reason:
            raise ValueError("unavailable evidence requires a reason")

    @classmethod
    def unavailable(cls, family: str, source: str, reason: str) -> "EvidenceProvenance":
        return cls(family, EvidenceQuality.UNAVAILABLE, source, reason=reason)

    def as_dict(self) -> Mapping[str, object]:
        return {
            "family": self.family,
            "quality": self.quality.value,
            "source": self.source,
            "as_of": self.as_of,
            "reason": self.reason,
        }
