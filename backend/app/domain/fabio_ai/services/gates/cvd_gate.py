"""CVD Gate — blocks entries when CVD strongly opposes direction.

Per Fabio methodology: "If CVD is strongly against you, NO TRADE."
This is a safety net — the LLM may miss extreme institutional pressure.

Market-aware thresholds:
- NSE: 5000 (higher volume, wider threshold)
- MCX: 50 (thinner books, tighter threshold)
"""

from __future__ import annotations

import logging

from app.domain.fabio_ai.services.gates.base import EntryGate, GateContext, GateResult

logger = logging.getLogger(__name__)


class CVDGate(EntryGate):
    """Blocks entries when CVD slope strongly opposes the intended direction."""

    @property
    def name(self) -> str:
        return "CVD"

    def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate CVD opposition.

        LONG blocked if CVD slope < -threshold (extreme selling).
        SHORT blocked if CVD slope > +threshold (extreme buying).
        """
        cvd_slope = context.cvd_slope
        threshold = context.cvd_threshold
        direction = context.direction

        if direction == "LONG" and cvd_slope < -threshold:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason="CVD_OPPOSING",
                detail=f"LONG blocked — CVD slope {cvd_slope:.0f} (extreme selling, threshold={threshold:.0f})",
                confidence_adjustment=-0.5,
            )

        if direction == "SHORT" and cvd_slope > threshold:
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason="CVD_OPPOSING",
                detail=f"SHORT blocked — CVD slope {cvd_slope:.0f} (extreme buying, threshold={threshold:.0f})",
                confidence_adjustment=-0.5,
            )

        return GateResult(
            passed=True,
            gate_name=self.name,
            reason="CVD_OK",
            detail=f"CVD slope {cvd_slope:.0f} within threshold ±{threshold:.0f}",
        )