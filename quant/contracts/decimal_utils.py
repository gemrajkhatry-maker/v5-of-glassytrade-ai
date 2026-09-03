# quant/contracts/decimal_utils.py
"""Thin re-export — owner is shared.money (REF-01)."""
from __future__ import annotations
from shared.money import to_decimal, safe_decimal_operation  # noqa: F401
__all__ = ["to_decimal", "safe_decimal_operation"]
