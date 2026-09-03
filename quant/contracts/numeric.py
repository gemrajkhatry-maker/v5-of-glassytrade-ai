# quant/contracts/numeric.py
"""Thin re-export — owner is shared.money (REF-01)."""
from __future__ import annotations

from shared.money import to_float  # noqa: F401

__all__ = ["to_float"]
