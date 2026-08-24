"""Unified decimal/float conversion utilities for financial calculations.

This module provides consistent type conversion across the codebase,
preventing precision errors in financial calculations.
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
    
    Raises:
        ValueError: If value cannot be converted to Decimal
    
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


def to_float(value: Any, default: float = 0.0) -> float:
    """Convert any numeric type to float.
    
    Args:
        value: Input value (float, int, str, or Decimal)
        default: Default value if conversion fails
    
    Returns:
        Float representation of the value
    
    Examples:
        >>> to_float(Decimal("123.45"))
        123.45
        >>> to_float("123.45")
        123.45
        >>> to_float(None)
        0.0
    """
    if value is None:
        return default
    
    if isinstance(value, float):
        return value
    
    if isinstance(value, int):
        return float(value)
    
    if isinstance(value, Decimal):
        return float(value)
    
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    
    if hasattr(value, '__float__'):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    
    return default


def safe_decimal_operation(
    a: Any,
    b: Any,
    operation: str = "add"
) -> Decimal:
    """Perform safe decimal operations with automatic conversion.
    
    Args:
        a: First operand
        b: Second operand
        operation: Operation type ("add", "subtract", "multiply", "divide")
    
    Returns:
        Result of the operation as Decimal
    
    Raises:
        ValueError: If operation is not supported
        ZeroDivisionError: If division by zero
    """
    dec_a = to_decimal(a)
    dec_b = to_decimal(b)
    
    if operation == "add":
        return dec_a + dec_b
    elif operation == "subtract":
        return dec_a - dec_b
    elif operation == "multiply":
        return dec_a * dec_b
    elif operation == "divide":
        if dec_b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return dec_a / dec_b
    else:
        raise ValueError(f"Unsupported operation: {operation}")


# Convenience functions for common operations
def decimal_add(a: Any, b: Any) -> Decimal:
    """Add two values as Decimals."""
    return safe_decimal_operation(a, b, "add")


def decimal_subtract(a: Any, b: Any) -> Decimal:
    """Subtract two values as Decimals."""
    return safe_decimal_operation(a, b, "subtract")


def decimal_multiply(a: Any, b: Any) -> Decimal:
    """Multiply two values as Decimals."""
    return safe_decimal_operation(a, b, "multiply")


def decimal_divide(a: Any, b: Any) -> Decimal:
    """Divide two values as Decimals."""
    return safe_decimal_operation(a, b, "divide")