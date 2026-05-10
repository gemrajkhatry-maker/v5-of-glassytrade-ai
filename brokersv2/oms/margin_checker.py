"""
Pre-order margin check against Dhan's fund limit API.

Calls ``GET /fundlimit`` before placing any order and rejects it early if the
available margin is insufficient, avoiding a broker-side rejection which is
harder to handle gracefully.

Margin multipliers (conservative defaults, caller can override):
    INTRADAY / MIS  → 0.20   (5x leverage → 20% margin required)
    CNC             → 1.00   (full cash delivery)
    MARGIN          → 0.50   (2x leverage)
    MTF             → 0.25   (4x leverage)
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.infrastructure.dhan_adapter.client import DhanHttpClient
    from brokersv2.domain.order.models import Order

logger = logging.getLogger(__name__)

# Default margin multipliers by product type (fraction of order value required)
_DEFAULT_MULTIPLIERS: dict[str, float] = {
    "INTRADAY": 0.20,
    "MIS":      0.20,
    "MARGIN":   0.50,
    "MTF":      0.25,
    "CNC":      1.00,
}


class MarginInsufficientError(Exception):
    """Raised when available margin is below the estimated requirement."""

    def __init__(
        self,
        required: float,
        available: float,
        product_type: str,
        symbol: str,
    ) -> None:
        self.required = required
        self.available = available
        self.product_type = product_type
        self.symbol = symbol
        super().__init__(
            f"Insufficient margin for {symbol} ({product_type}): "
            f"required ₹{required:,.2f}, available ₹{available:,.2f}"
        )


class MarginChecker:
    """
    Pre-order margin guard.

    Usage::

        checker = MarginChecker(http_client)
        await checker.check(order)   # raises MarginInsufficientError if short

    The check is intentionally conservative: it uses the ask price (or limit
    price) and the product-type multiplier to estimate the gross margin needed.
    SEBI PEAK margin norms apply; this checker ensures at least the estimated
    delivery margin is available before sending the order.
    """

    def __init__(
        self,
        http_client: "DhanHttpClient",
        margin_multipliers: Optional[dict] = None,
        safety_buffer: float = 0.05,
    ) -> None:
        """
        Args:
            http_client: DhanHttpClient instance for the fund-limit API call.
            margin_multipliers: Override per-product-type multipliers.
            safety_buffer: Additional buffer (default 5%) on top of the
                computed required margin to handle price slippage.
        """
        self._client = http_client
        self._multipliers = {**_DEFAULT_MULTIPLIERS, **(margin_multipliers or {})}
        self._safety_buffer = safety_buffer

    async def check(self, order: "Order") -> None:
        """
        Fetch fund limit and raise MarginInsufficientError if margin is short.

        Args:
            order: The candidate order to check.

        Raises:
            MarginInsufficientError: if available_balance < required_margin.
        """
        product_type = getattr(order, "product_type", None)
        product_type_str = product_type.value if product_type is not None else "CNC"
        multiplier = self._multipliers.get(product_type_str.upper(), 1.0)

        price = float(order.price or Decimal("0"))
        quantity = int(order.quantity)

        # Use a nominal price of 0 for MARKET orders — skip margin check since
        # we don't know the fill price; the broker will reject if insufficient.
        if price <= 0:
            logger.debug(
                "MarginChecker: MARKET order for %s — skipping (unknown fill price)",
                order.instrument.symbol,
            )
            return

        required = price * quantity * multiplier * (1.0 + self._safety_buffer)

        try:
            fund_data = await self._client.get_fund_limit()
        except Exception as exc:
            # Under SEBI PEAK margin rules, an unknown available balance must be
            # treated as zero — silently proceeding risks a margin call at EOD.
            logger.critical(
                "MarginChecker: GET /fundlimit FAILED (%s) — REJECTING order for %s "
                "to prevent margin breach. Fix connectivity before retrying.",
                exc, order.instrument.symbol,
            )
            raise MarginInsufficientError(
                required=required,
                available=0.0,
                product_type=product_type_str,
                symbol=order.instrument.symbol,
            ) from exc

        # DhanHQ /fundlimit response keys (may vary by API version)
        available = float(
            fund_data.get("availabelBalance",
            fund_data.get("availableBalance",
            fund_data.get("net",
            fund_data.get("withdrawableBalance", 0))))
        )

        logger.debug(
            "MarginChecker: %s qty=%d @ %.2f | required=%.2f available=%.2f",
            order.instrument.symbol, quantity, price, required, available,
        )

        if available < required:
            raise MarginInsufficientError(
                required=required,
                available=available,
                product_type=product_type_str,
                symbol=order.instrument.symbol,
            )
