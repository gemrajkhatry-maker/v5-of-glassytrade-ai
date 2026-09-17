"""Decision result dict factory eliminates copy-paste duplication."""
from quant.decision.result_factory import build_decision_result, build_gate_results


def test_build_decision_result_contains_all_required_keys():
    result = build_decision_result(
        role="SCANNING",
        action="FLAT",
        direction="FLAT",
        setup="NO_EDGE",
        reason="NO_PROFILE",
        confidence="Low",
        confidence_score=0.0,
        rationale="No profile yet",
        forecast=None,
        gate_results=[],
        active_position=None,
        symbol="NIFTY24DEC21500CE",
        entry_price=0.0,
        market_state="BALANCED",
        session_phase="REGULAR",
    )
    required_keys = {
        "role", "action", "direction", "setup", "reason",
        "confidence", "confidenceScore", "rationale",
        "forecastSteps", "quantileSpread", "meanForecast",
        "gateResults", "activePosition", "dynamicTrailStop",
        "source", "latencyMs", "modelLabel", "modelVersions",
        "regime", "timing", "sizeFraction", "latencyUs",
    }
    assert required_keys.issubset(set(result.keys()))


def test_regime_resolves_from_string():
    result = build_decision_result(
        role="SCANNING", action="FLAT", direction="FLAT",
        setup="NO_EDGE", reason="TEST", confidence="Low",
        confidence_score=0.0, rationale="test",
        forecast=None, gate_results=[],
        active_position=None, symbol="TEST",
        entry_price=0.0,
        market_state="TRENDING",
        session_phase="REGULAR",
    )
    assert result["regime"] == "TRENDING"


def test_timing_defaults_to_regular():
    result = build_decision_result(
        role="SCANNING", action="FLAT", direction="FLAT",
        setup="NO_EDGE", reason="TEST", confidence="Low",
        confidence_score=0.0, rationale="test",
        forecast=None, gate_results=[],
        active_position=None, symbol="TEST",
        entry_price=0.0,
        market_state="BALANCED",
        session_phase=None,
    )
    assert result["timing"] == "REGULAR"


def test_build_gate_results_structure():
    gates = build_gate_results(
        g1_passed=True, g1_msg="Session open",
        g2_passed=True, g2_msg="No cooldown",
        g3_passed=False, g3_msg="No edge",
        g4_passed=False, g4_msg="No setup",
    )
    assert len(gates) == 4
    assert gates[0]["gate_no"] == 1
    assert gates[0]["gate_name"] == "SESSION_PHASE"
    assert gates[0]["passed"] is True
    assert gates[2]["passed"] is False
