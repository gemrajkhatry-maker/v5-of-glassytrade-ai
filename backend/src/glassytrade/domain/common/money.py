"""Decimal-safe money primitives for domain boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool) or value is None:
        raise ValueError("money value must be numeric")
    else:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid money value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("money value must be finite")
    return result


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = "INR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency must be a non-empty string")

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError("currency mismatch")
