"""Contested Zone Gate — blocks entries when both BUY and SELL stacked imbalances exist.

Per Fabio methodology: When both sides show stacked imbalances, the market
is contested — neither side has control. Best action is FLAT.
"""

from __future__ import annotations

import logging

from app.domain.fabio_ai.services.gates.base import EntryGate, GateContext, GateResult

logger = logging.getLogger(__name__)


class ContestedZoneGate(EntryGate):
    """Blocks entries when both BUY and SELL stacked imbalances exist."""

    @property
    def name(self) -> str:
        return "CONTESTED_ZONE"

    def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate contested zone presence.

        Returns False if both BUY and SELL stacked imbalances exist
        in the recent footprint data.
        """
        fp_candle = context.footprint_candle

        if fp_candle is None:
            return GateResult(
                passed=True,
                gate_name=self.name,
                reason="NO_FOOTPRINT",
                detail="No footprint data available",
            )

        if not hasattr(fp_candle, "levels") or not fp_candle.levels:
            return GateResult(
                passed=True,
                gate_name=self.name,
                reason="NO_LEVELS",
                detail="No footprint levels available",
            )

        # Check for stacked imbalances
        has_buy_stacked = False
        has_sell_stacked = False

        for level in fp_candle.levels:
            if getattr(level, "stacked", False):
                delta = getattr(level, "delta", 0)
                if delta > 0:
                    has_buy_stacked = True
                elif delta < 0:
                    has_sell_stacked = True

        if has_buy_stacked and has_sell_stacked:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason="CONTESTED_ZONE",
                detail=f"Both BUY and SELL stacked imbalances present — market contested, neither side has control",
                confidence_adjustment=-0.5,
            )

        return GateResult(
            passed=True,
            gate_name=self.name,
            reason="NO_CONTEST",
            detail="No contested zone detected",
        )