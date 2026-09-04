from quantv2.types import Bar
from quantv2.amt import SessionAMT


def test_profile_and_break_keys():
    amt = SessionAMT(tick=1.0)
    for i in range(20):
        amt.update(Bar(time=f"t{i}", open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0, delta=1.0))
    snap = amt.update(Bar(time="t20", open=100.0, high=103.0, low=100.0, close=103.0, volume=50.0, delta=20.0))
    assert snap["vah"] is not None and snap["val"] is not None and snap["poc"] is not None
    assert snap["break_type"] == "INITIATIVE" and snap["break_dir"] == "UP"
    assert set(("leg_lvn", "absorption")) <= set(snap["extra"])
