"""Decimal utilities — domain-friendly decimal conversion.

Moved from shared/conversion.py to maintain domain layer isolation.
No imports from infrastructure or shared modules.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def to_decimal(value: Any) -> Decimal:
    """Convert any numeric type to Decimal for precise financial calculations.

    Args:
        value: Input value (float, int, str, or Decimal)

    Returns:
        Decimal representation of the value

    Examples:
        >>> to_decimal(123.45)
        Decimal('123.45')
        >>> to_decimal("123.45")
        Decimal('123.45')
        >>> to_decimal(Decimal("123.45"))
        Decimal('123.45')
    """
    if isinstance(value, Decimal):
        return value

    if value is None:
        return Decimal("0")

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise ValueError(f"Cannot convert '{value}' to Decimal")

    raise ValueError(f"Unsupported type: {type(value)}")
