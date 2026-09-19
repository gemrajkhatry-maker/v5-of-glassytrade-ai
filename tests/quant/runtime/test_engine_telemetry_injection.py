"""The engine no longer carries a telemetry sink on the decision loop.

The telemetry injection path was removed from the DecisionLoop — the loop
has no ``_telemetry`` attribute. These tests verify the absence.
"""

from __future__ import annotations

from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks


def _engine() -> QuantEngine:
    return QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)


def test_decision_loop_has_no_telemetry_attribute():
    engine = _engine()

    assert not hasattr(engine._decision_loop, "_telemetry")


def test_two_engines_construct_without_telemetry():
    engine_a = _engine()
    engine_b = _engine()

    assert not hasattr(engine_a._decision_loop, "_telemetry")
    assert not hasattr(engine_b._decision_loop, "_telemetry")
