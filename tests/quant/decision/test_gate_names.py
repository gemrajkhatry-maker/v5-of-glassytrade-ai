from quant.decision.result import GateResult, GATE_NAMES

def test_every_pipeline_gate_has_a_name():
    # gates 1..4 from the simplified Fabio pipeline
    for n in range(1, 5):
        r = GateResult(gate=n, passed=True)
        assert r.name == GATE_NAMES[n]

def test_unknown_gate_falls_back():
    r = GateResult(gate=99, passed=False)
    assert r.name == "GATE_99"

def test_gate_result_is_still_frozen():
    r = GateResult(gate=1, passed=True)
    try:
        r.gate = 2
        assert False, "should not be mutable"
    except Exception:
        pass  # dataclass frozen raises FrozenInstanceError
