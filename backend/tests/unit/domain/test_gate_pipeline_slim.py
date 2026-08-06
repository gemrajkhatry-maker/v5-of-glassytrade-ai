from app.domain.fabio_ai.services.gate_pipeline import GateContext


def test_gate_context_has_triple_a_fields_with_defaults():
    ctx = GateContext()
    assert ctx.triple_a_phase == ""
    assert ctx.absorption_detected is False
    assert ctx.absorption_bar_age == 0
    assert ctx.vwap_breakout is None


def test_gate_context_accepts_explicit_values():
    ctx = GateContext(
        triple_a_phase="AGGRESSION",
        absorption_detected=True,
        absorption_bar_age=2,
        vwap_breakout="LONG",
    )
    assert ctx.triple_a_phase == "AGGRESSION"
    assert ctx.absorption_bar_age == 2
    assert ctx.vwap_breakout == "LONG"
