"""Liquidity Filter — filters option contracts by liquidity criteria.

Filters applied:
- Minimum OI (varies by underlying)
- Minimum volume in recent window
- Maximum bid-ask spread (basis points)
- Minimum LTP (avoid near-zero premium contracts)
"""

from __future__ import annotations

from dataclasses import dataclass
from appv2.config import constants as C


@dataclass
class LiquidityFilter:
    """Filters option contracts by liquidity."""

    min_oi: int = C.OPTION_MIN_OI_NIFTY
    min_volume_5min: int = C.OPTION_MIN_VOLUME_5MIN
    max_spread_bps: int = C.OPTION_MAX_SPREAD_BPS
    min_ltp: float = 5.0  # Minimum premium price

    def filter(
        self,
        contracts: list[dict],
        underlying: str = "",
    ) -> list[dict]:
        """Filter contracts by liquidity criteria.

        Args:
            contracts: List of option contract dicts with keys:
                       oi, volume, spread_bps, ltp, strike_price
            underlying: Underlying symbol (for OI threshold adjustment)

        Returns:
            Filtered list of liquid contracts
        """
        # Adjust OI threshold by underlying
        min_oi = self._get_min_oi(underlying)

        filtered = []
        for c in contracts:
            # OI check
            if c.get("oi", 0) < min_oi:
                continue
            # Volume check
            if c.get("volume", 0) < self.min_volume_5min:
                continue
            # Spread check
            spread_bps = c.get("spread_bps", 0)
            if spread_bps > self.max_spread_bps:
                continue
            # LTP check
            ltp = c.get("ltp", 0)
            if ltp < self.min_ltp:
                continue

            filtered.append(c)

        return filtered

    def is_liquid(self, contract: dict, underlying: str = "") -> bool:
        """Check single contract for liquidity."""
        min_oi = self._get_min_oi(underlying)
        return (
            contract.get("oi", 0) >= min_oi
            and contract.get("volume", 0) >= self.min_volume_5min
            and contract.get("spread_bps", float("inf")) <= self.max_spread_bps
            and contract.get("ltp", 0) >= self.min_ltp
        )

    def _get_min_oi(self, underlying: str) -> int:
        upper = underlying.upper()
        if "NIFTY" in upper:
            return C.OPTION_MIN_OI_NIFTY
        elif "BANKNIFTY" in upper:
            return C.OPTION_MIN_OI_BANKNIFTY
        return self.min_oi  # Default
