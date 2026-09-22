"""Port for option Greeks — delta per contract for sizing/translation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class GreeksPort(Protocol):
    """Returns the option Greek delta for a contract, or None when unknown.

    Money-path rule: missing delta is DATA_DEGRADED — never invent 0.50.
    """

    def delta(self, symbol: str) -> float | None:
        """Absolute delta in (0, 1], or None when the chain has no quote."""
        ...


@runtime_checkable
class OptionChainPort(Protocol):
    """Resolves a long option contract for a directional certificate.

    Bearish certificates buy puts; bullish certificates buy calls.
    Naked option shorts are never produced.
    """

    def select_long_call(self, *, underlying: str, spot: float) -> str | None:
        ...

    def select_long_put(self, *, underlying: str, spot: float) -> str | None:
        ...


class DictGreeks:
    """In-memory GreeksPort — coordinator/scanner fills deltas per contract."""

    def __init__(self, mapping: dict[str, float] | None = None) -> None:
        self._m: dict[str, float] = dict(mapping or {})

    def set_delta(self, symbol: str, value: float) -> None:
        d = float(value)
        if 0.0 < abs(d) <= 1.0:
            self._m[str(symbol)] = abs(d)

    def delta(self, symbol: str) -> float | None:
        v = self._m.get(str(symbol))
        if v is None:
            return None
        d = float(v)
        return d if 0.0 < abs(d) <= 1.0 else None
