"""Stable identifiers for canonical domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContractId:
    exchange: str
    root: str
    expiry: str
    instrument_type: str
    strike: str | None
    option_type: str
    security_id: str

    def __post_init__(self) -> None:
        required = {
            "exchange": self.exchange,
            "root": self.root,
            "expiry": self.expiry,
            "instrument_type": self.instrument_type,
            "option_type": self.option_type,
            "security_id": self.security_id,
        }
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.strike is not None and (
            not isinstance(self.strike, str) or not self.strike.strip()
        ):
            raise ValueError("strike must be a non-empty string or None")

    @property
    def key(self) -> str:
        return "|".join(
            (
                self.exchange,
                self.root,
                self.expiry,
                self.instrument_type,
                self.strike or "",
                self.option_type,
                self.security_id,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "root": self.root,
            "expiry": self.expiry,
            "instrument_type": self.instrument_type,
            "strike": self.strike,
            "option_type": self.option_type,
            "security_id": self.security_id,
        }
