"""Momentum Fade Gate — blocks entries that fade a freight train.

Per Fabio Rule: "Don't short a 2.5 sigma bullish impulse on the first touch
if it has no meaningful rejection wick. (Same for long on bearish impulse)."

This prevents the system from fighting extreme momentum moves.
"""

from __future__ import annotations

from app.domain.services.candle_metrics import body as calc_body

import logging
import math

from app.domain.fabio_ai.services.gates.base import EntryGate, GateContext, GateResult

logger = logging.getLogger(__name__)


class MomentumFadeGate(EntryGate):
    """Blocks entries that fade extreme momentum moves."""

    @property
    def name(self) -> str:
        return "MOMENTUM_FADE"

    def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate momentum fade risk.

        Returns False if attempting to fade a freight train (2.5σ impulse
        with no rejection wick).
        """
        data = context.session_data
        tick = context.tick
        direction = context.direction

        if not data or len(data) < 20 or tick.volume <= 0:
            return GateResult(
                passed=True,
                gate_name=self.name,
                reason="NO_DATA",
                detail="Insufficient data for momentum fade check",
            )

        # Compute EMA(20) volume
        alpha = 2.0 / 21
        ema_vol = data[-20].volume
        for d in data[-19:]:
            ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol

        # Is it a massive volume spike (2.5σ)?
        if tick.volume < (ema_vol * 2.5):
            return GateResult(
                passed=True,
                gate_name=self.name,
                reason="NO_SPIKE",
                detail=f"Volume {tick.volume:.0f} < 2.5σ ({ema_vol * 2.5:.0f})",
            )

        # Check if it's a strong directional candle (body > 70% of range)
        body_size = calc_body(tick.open, tick.high, tick.low, tick.close)
        candle_range = tick.high - tick.low

        if candle_range <= 0 or body < (candle_range * 0.70):
            return GateResult(
                passed=True,
                gate_name=self.name,
                reason="WEAK_CANDLE",
                detail="Candle body too small for momentum fade check",
            )

        upper_wick = tick.high - max(tick.open, tick.close)
        lower_wick = min(tick.open, tick.close) - tick.low

        # Block SHORT entries against strong BULLISH momentum (no rejection wick)
        if direction == "SHORT" and tick.close > tick.open:
            if upper_wick < (body * 0.3):
                return GateResult(
                    passed=False,
                    gate_name=self.name,
                    reason="MOMENTUM_FADE",
                    detail=f"SHORT blocked — fading 2.5σ bullish impulse without rejection wick (vol={tick.volume:.0f}, ema={ema_vol:.0f})",
                    confidence_adjustment=-0.5,
                )

        # Block LONG entries against strong BEARISH momentum (no rejection wick)
        if direction == "LONG" and tick.close < tick.open:
            if lower_wick < (body * 0.3):
                return GateResult(
                    passed=False,
                    gate_name=self.name,
                    reason="MOMENTUM_FADE",
                    detail=f"LONG blocked — fading 2.5σ bearish impulse without rejection wick (vol={tick.volume:.0f}, ema={ema_vol:.0f})",
                    confidence_adjustment=-0.5,
                )

        return GateResult(
            passed=True,
            gate_name=self.name,
            reason="MOMENTUM_OK",
            detail="No momentum fade risk detected",
        )
