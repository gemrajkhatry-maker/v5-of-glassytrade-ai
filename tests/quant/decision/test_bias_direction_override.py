"""15-min bias overrides direction when confidence is high."""
from quant.amt.bias.bias_resolver import BiasDirection, BiasResult
from quant.decision.context_builder import _apply_bias_override


def test_bias_overrides_neutral_direction():
    """When AMT direction is neutral but bias is strong LONG, bias wins."""
    result = _apply_bias_override(
        current_direction="FLAT",
        bias=BiasResult(
            direction=BiasDirection.LONG_BIAS,
            confidence=0.8,
            higher_highs=True, higher_lows=True,
            lower_highs=False, lower_lows=False,
        ),
    )
    assert result == "LONG"


def test_bias_does_not_override_opposing_strong_direction():
    """When AMT already has strong SHORT, weak LONG bias does not override."""
    result = _apply_bias_override(
        current_direction="SHORT",
        bias=BiasResult(
            direction=BiasDirection.LONG_BIAS,
            confidence=0.4,  # below threshold
            higher_highs=True, higher_lows=False,
            lower_highs=False, lower_lows=True,
        ),
    )
    assert result == "SHORT"


def test_neutral_bias_does_not_change_direction():
    """Neutral bias leaves existing direction unchanged."""
    result = _apply_bias_override(
        current_direction="LONG",
        bias=BiasResult(
            direction=BiasDirection.NEUTRAL,
            confidence=0.0,
            higher_highs=False, higher_lows=False,
            lower_highs=False, lower_lows=False,
        ),
    )
    assert result == "LONG"
