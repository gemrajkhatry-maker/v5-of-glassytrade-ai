"""Deprecated: Use app.domain.fabio_ai.services.gate_pipeline instead.

This module exists only for backward compatibility with legacy imports.
ServiceGraph has been eliminated (ADR-0003).
"""

from app.domain.fabio_ai.services.gate_pipeline import (
    GatePipeline,
    GateContext,
    GateResult,
    GateType,
    GateReason,
)

__all__ = ["GatePipeline", "GateContext", "GateResult", "GateType", "GateReason"]
