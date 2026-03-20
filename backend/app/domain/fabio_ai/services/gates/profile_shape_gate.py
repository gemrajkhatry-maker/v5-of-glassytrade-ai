"""Profile Shape Gate — blocks entries opposing dominant distribution shape.

Per Fabio methodology:
- P-shape (top-heavy): sellers may be trapped above → LONG blocked
- b-shape (bottom-heavy): buying absorption below → SHORT blocked
"""

from __future__ import annotations

import logging

from app.domain.fabio_ai.services.gates.base import EntryGate, GateContext, GateResult

logger = logging.getLogger(__name__)


class ProfileShapeGate(EntryGate):
    """Blocks entries that oppose the dominant volume profile shape."""

    @property
    def name(self) -> str:
        return "PROFILE_SHAPE"

    def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate profile shape alignment.

        P-shape: LONG blocked (sellers trapped above — expect rejection)
        b-shape: SHORT blocked (buyers absorbing below — expect bounce)
        """
        shape = context.profile_shape
        direction = context.direction

        if direction == "LONG" and shape == "P":
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason="PROFILE_SHAPE_P",
                detail=f"LONG blocked — P-shape (top-heavy distribution, sellers trapped above)",
                confidence_adjustment=-0.3,
            )

        if direction == "SHORT" and shape == "b":
            return GateResult(
                passed=False,
                gate_name=self.name,
                reason="PROFILE_SHAPE_B",
                detail=f"SHORT blocked — b-shape (bottom accumulation, buyers absorbing)",
                confidence_adjustment=-0.3,
            )

        return GateResult(
            passed=True,
            gate_name=self.name,
            reason="SHAPE_OK",
            detail=f"Profile shape {shape} aligned with {direction}",
        )