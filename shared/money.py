# shared/money.py
"""Sole numeric vocabulary — Decimal/float conversions. (REF-01)"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Any

def to_decimal(value: Any) -> Decimal:
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
    if hasattr(value, "__float__"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default

def safe_decimal_operation(a: Any, b: Any, operation: str = "add") -> Decimal:
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
    raise ValueError(f"Unsupported operation: {operation}")
