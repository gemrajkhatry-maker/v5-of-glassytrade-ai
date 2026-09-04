from quantv2.replay import compare_tapes, run_tape

TAPE = [
    {"time": "t1", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0, "vah": 101.0, "val": 99.0, "poc": 100.2, "cvd": 0.3, "extra": {}, "submitted": True},
    {"time": "t2", "open": 100.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 50.0, "vah": 101.0, "val": 99.0, "poc": 100.8, "cvd": 0.3,
     "extra": {"triple_phase": "AGGRESSION", "triple_signal": "LONG", "acceptance": True}, "submitted": True},
]


def test_real_tape_one_approval():
    r = run_tape(TAPE)
    assert r["approvals"] == 1 and r["phantoms"] == 0 and r["min_rr"] >= 1.5 and r["monotonic_ok"] is True


def test_compare_tapes_subset():
    assert compare_tapes(3, 1) is True
    assert compare_tapes(1, 2) is False
