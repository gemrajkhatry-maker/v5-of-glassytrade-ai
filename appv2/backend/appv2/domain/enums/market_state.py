"""Market state enum — Fabio AMT 4-state classification."""

from __future__ import annotations

from enum import Enum


class MarketState(str, Enum):
    """Auction market states per Fabio Valentini."""

    NO_TRADE = "NO_TRADE"  # Price at POC dead zone
    BALANCED = "BALANCED"  # Price inside VA, rotational
    IMBALANCED = "IMBALANCED"  # Price outside VA + displacement + acceptance
    PROBING = "PROBING"  # Price outside VA without confirmation
