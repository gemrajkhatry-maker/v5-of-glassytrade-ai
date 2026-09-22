"""Architecture ratchet: typed AnalysisSnapshot seam on engine and context builder.

Money-path analysis→decision prefers ``AnalysisSnapshot`` (from ``AMTResult``);
the camelCase DTO remains for WS and compat fallbacks. These tests fail if the
public seam is removed or renamed after Tasks 2–3.
"""

from __future__ import annotations

import inspect

from quant.amt_engine import AMTEngine
from quant.decision.context_builder import DecisionContextBuilder


def test_amt_engine_exposes_last_snapshot_property():
    assert hasattr(AMTEngine, "last_snapshot")


def test_context_builder_build_accepts_snapshot_param():
    sig = inspect.signature(DecisionContextBuilder.build)
    assert "snapshot" in sig.parameters
