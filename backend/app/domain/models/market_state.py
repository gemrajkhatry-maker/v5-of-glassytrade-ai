"""Typed domain objects for market state with invariant enforcement.

All domain objects are frozen dataclasses that carry session_id and
instrument_key so cross-contamination is detectable at runtime.
Construction fails loudly if any invariant is violated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class InvariantError(ValueError):
    """Raised when a domain object invariant is violated."""

    pass


@dataclass(frozen=True)
class VolumeProfile:
    """Immutable volume profile with structural invariants.

    Invariants:
        - val < poc < vah (price ordering)
        - All prices must be positive
    """

    session_id: str
    instrument_key: str
    val: float
    poc: float
    vah: float
    total_volume: float
    computed_at: str

    def __post_init__(self) -> None:
        if self.val <= 0 or self.poc <= 0 or self.vah <= 0:
            raise InvariantError(
                f"Volume profile prices must be positive: "
                f"val={self.val}, poc={self.poc}, vah={self.vah}"
            )
        if self.val >= self.poc:
            raise InvariantError(
                f"VAL ({self.val}) >= POC ({self.poc}) — "
                f"session={self.session_id}, instrument={self.instrument_key}"
            )
        if self.poc >= self.vah:
            raise InvariantError(
                f"POC ({self.poc}) >= VAH ({self.vah}) — "
                f"session={self.session_id}, instrument={self.instrument_key}"
            )


@dataclass(frozen=True)
class VWAPState:
    """Immutable VWAP state with sign-direction contract.

    Invariants:
        - sigma >= 0
        - vwap > 0
        - deviation_sigmas sign matches (LTP - VWAP) direction
    """

    session_id: str
    instrument_key: str
    vwap: float
    sigma: float
    upper_1: float
    lower_1: float
    upper_2: float
    lower_2: float
    deviation_sigmas: float
    computed_at: str

    def __post_init__(self) -> None:
        if self.sigma < 0:
            raise InvariantError(f"Negative sigma: {self.sigma}")
        if self.vwap <= 0:
            raise InvariantError(f"Non-positive VWAP: {self.vwap}")
        if self.sigma > 0 and self.deviation_sigmas != 0:
            implied_price = self.vwap + self.deviation_sigmas * self.sigma
            expected_positive = implied_price > self.vwap
            actual_positive = self.deviation_sigmas > 0
            if expected_positive != actual_positive:
                raise InvariantError(
                    f"VWAP deviation sign mismatch: deviation={self.deviation_sigmas}, "
                    f"vwap={self.vwap}, sigma={self.sigma}, implied_price={implied_price}"
                )


@dataclass(frozen=True)
class MarketMetrics:
    """Immutable market metrics snapshot.

    Invariants:
        - balance_pct in [0.0, 1.0]
    """

    session_id: str
    instrument_key: str
    delta: float
    cvd_slope: float
    ofi: float
    balance_pct: float
    profile_shape: str
    aggression_score: float
    computed_at: str

    def __post_init__(self) -> None:
        if not (0.0 <= self.balance_pct <= 1.0):
            raise InvariantError(f"Balance pct out of range [0, 1]: {self.balance_pct}")


@dataclass(frozen=True)
class IndicatorLineage:
    """Provenance tracking for every indicator value.

    Makes drift immediately detectable: if two indicators have different
    session_id or instrument_key, the UI can flag a DATA_ANOMALY.
    """

    indicator: str
    source: str
    bar_count: int
    session_id: str
    instrument_key: str
    computed_at: str


@dataclass(frozen=True)
class RuleChecklistResult:
    """Immutable rule checklist result for display and gating.

    Invariants:
        - passed <= total
        - total > 0
    """

    passed: int
    total: int
    gate_failures: list[str]
    computed_at: str

    def __post_init__(self) -> None:
        if self.total <= 0:
            raise InvariantError(f"Rule checklist total must be > 0: {self.total}")
        if self.passed > self.total:
            raise InvariantError(f"Passed ({self.passed}) > total ({self.total})")


@dataclass(frozen=True)
class SessionContext:
    """Immutable session identity.

    Carries enough information to detect cross-session contamination:
    if an analysis result's session_id doesn't match the current session,
    it's stale data from a prior day or instrument.
    """

    session_id: str
    instrument_key: str
    exchange: str
    phase: str
    start_ts: str
    end_ts: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise InvariantError("Session ID cannot be empty")
        if not self.instrument_key:
            raise InvariantError("Instrument key cannot be empty")
