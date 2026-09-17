"""15-min bias integrates into decision context as direction override."""
import pytest
from quant.amt.bias.bias_resolver import BiasDirection, BiasResult
from quant.decision.context import DecisionContext


def test_decision_context_has_bias_fields():
    """DecisionContext carries bias_direction and bias_confidence."""
    ctx = DecisionContext(
        symbol="NIFTY24DEC21500CE",
        session_phase="REGULAR",
        bias_direction=BiasDirection.LONG_BIAS,
        bias_confidence=0.8,
    )
    assert ctx.bias_direction == BiasDirection.LONG_BIAS
    assert ctx.bias_confidence == 0.8


def test_bias_defaults_to_neutral():
    """DecisionContext defaults bias to NEUTRAL when not provided."""
    ctx = DecisionContext(
        symbol="NIFTY24DEC21500CE",
        session_phase="REGULAR",
    )
    assert ctx.bias_direction == BiasDirection.NEUTRAL
    assert ctx.bias_confidence == 0.0
