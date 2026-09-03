"""Sole lot-snapping helper. (REF-06)"""
from __future__ import annotations

import math

__all__ = ["snap_to_lot"]


def snap_to_lot(quantity: float, lot_size: float) -> float:
    """Round a raw unit count to the nearest lot multiple (min 1 lot).

    Half-lots round UP: banker's rounding (round(2.5)=2) silently
    under-sized pyramid P2 by 20% (certification S10 finding).
    """
    if lot_size is None or lot_size <= 0 or quantity <= 0:
        return quantity
    num_lots = max(1.0, math.floor(quantity / lot_size + 0.5))
    return num_lots * lot_size
