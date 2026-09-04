from quantv2.replay import run_tape

def test_replay_gate_no_phantom():
    tapes = run_tape([])
    assert tapes["approved_without_position"] == 0
