from quantv2.risk import gate, size

def test_halted_rejects_before_approval():
    assert gate(False, 0.0, False, 1) == "HALTED"
    assert gate(True, 0.0, False, 1) is None
    assert size(100000.0, 0.005, 100.0, 99.0, 1) > 0
