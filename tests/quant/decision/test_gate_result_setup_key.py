from quant.decision.result import GateResult


def test_gate_result_carries_setup_key_defaulting_empty():
    assert GateResult(3, True, "ok").setup_key == ""
    assert GateResult(3, True, "ok", setup_key="TRIPLE_A").setup_key == "TRIPLE_A"
