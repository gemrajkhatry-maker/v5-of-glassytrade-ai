"""Deprecated: Use app.domain.fabio_ai.services.gate_pipeline instead.

This module exists only for backward compatibility with legacy imports
in service_graph.py and api/dependencies.py.
"""

from app.domain.fabio_ai.services.gate_pipeline import (
    GatePipeline,
    GateContext,
    GateResult,
    GateType,
    GateReason,
)

__all__ = ["GatePipeline", "GateContext", "GateResult", "GateType", "GateReason"]
