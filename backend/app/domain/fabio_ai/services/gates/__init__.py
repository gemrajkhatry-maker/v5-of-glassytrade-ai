"""Gate chain — extensible entry gate evaluation per Fabio AMT spec.

Each gate is an independent, testable unit that evaluates a specific condition.
The GateChain runs gates sequentially and returns the first failure.

Usage:
    chain = GateChain([
        CVDGate(),
        ProfileShapeGate(),
        MomentumFadeGate(),
        ContestedZoneGate(),
    ])
    result = chain.evaluate(context)
    if not result.passed:
        # Entry blocked by gate
        logger.info("Gate %s blocked: %s", result.gate_name, result.detail)
"""

from app.domain.fabio_ai.services.gates.base import (
    GateContext,
    GateResult,
    EntryGate,
    GateChain,
)
from app.domain.fabio_ai.services.gates.cvd_gate import CVDGate
from app.domain.fabio_ai.services.gates.profile_shape_gate import ProfileShapeGate
from app.domain.fabio_ai.services.gates.momentum_fade_gate import MomentumFadeGate
from app.domain.fabio_ai.services.gates.contested_zone_gate import ContestedZoneGate

__all__ = [
    "GateContext",
    "GateResult",
    "EntryGate",
    "GateChain",
    "CVDGate",
    "ProfileShapeGate",
    "MomentumFadeGate",
    "ContestedZoneGate",
]