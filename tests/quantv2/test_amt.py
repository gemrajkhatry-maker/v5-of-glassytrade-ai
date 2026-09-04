from quantv2.types import Bar
from quantv2.amt import SessionAMT
from quantv2.types import Context
from quantv2.setups import detect


def test_profile_and_break_keys():
    amt = SessionAMT(tick=1.0)
    for i in range(20):
        amt.update(Bar(time=f"t{i}", open=100.0, high=101.0, low=99.0, close=100.0, volume=10.0, delta=1.0))
    snap = amt.update(Bar(time="t20", open=100.0, high=103.0, low=100.0, close=103.0, volume=50.0, delta=20.0))
    assert snap["vah"] is not None and snap["val"] is not None and snap["poc"] is not None
    assert snap["break_type"] == "INITIATIVE" and snap["break_dir"] == "UP"
    assert set(("leg_lvn", "absorption")) <= set(snap["extra"])


def _bars():
    # absorption: heavy selling (delta<0) but price closes UP — buyers absorbed the sellers (bullish)
    return [
        Bar(time="t1", open=99.2, high=100.4, low=99.0, close=100.2, volume=100.0, delta=-60.0),
        Bar(time="t2", open=100.2, high=100.5, low=100.0, close=100.3, volume=20.0, delta=8.0),
        Bar(time="t3", open=100.3, high=100.6, low=100.1, close=100.5, volume=20.0, delta=9.0),
        Bar(time="t4", open=100.5, high=101.2, low=100.4, close=101.0, volume=60.0, delta=45.0),
        Bar(time="t5", open=101.0, high=101.3, low=100.9, close=101.1, volume=30.0, delta=12.0),
    ]


def test_triple_a_contract_reaches_detect():
    amt = SessionAMT(tick=0.05)
    for b in _bars():
        snap = amt.update(b)
    assert snap["extra"].get("triple_phase") == "AGGRESSION" and snap["extra"].get("triple_signal") == "LONG"
    ctx = Context(symbol="X", bar=_bars()[-1], tick=0.05, **{k: snap[k] for k in ("vah", "val", "poc", "cvd_slope")}, extra=snap["extra"])
    hit = detect(ctx)
    assert hit is not None and hit[0] in ("TRIPLE_A", "INITIATIVE")


def test_second_drive_rejected_short():
    amt = SessionAMT(tick=0.05)
    bars = [
        Bar(time="d1", open=100.0, high=100.9, low=99.9, close=100.8, volume=30.0, delta=20.0),  # drive 1 up (high 100.9)
        Bar(time="d2", open=100.8, high=100.9, low=100.0, close=100.1, volume=20.0, delta=-12.0),  # rejected: leg_rng 0.9
        Bar(time="d3", open=100.1, high=100.85, low=100.0, close=100.3, volume=15.0, delta=-10.0),  # weaker (0.85), pokes 100.8+, rejected
    ]
    for b in bars:
        snap = amt.update(b)
    x = snap["extra"]
    assert x.get("is_second_drive") is True and x.get("rejection") is True and x.get("direction") == "SHORT"


def test_cvd_scale_reaches_va_fade():
    amt = SessionAMT(tick=0.05)
    levels = [100.0, 100.1, 100.2, 100.3, 100.4]
    bars = [Bar(time=f"v{i}", open=100.0, high=100.5, low=99.9, close=levels[i % 5], volume=10.0, delta=2.0) for i in range(20)]
    dump1 = Bar(time="v20", open=99.6, high=99.7, low=99.4, close=99.5, volume=10.0, delta=4.0)
    dump2 = Bar(time="v21", open=99.55, high=99.6, low=99.35, close=99.55, volume=10.0, delta=4.0)
    for b in bars:
        snap = amt.update(b)
    amt.update(dump1)  # first dump fires INITIATIVE DOWN (priority); fade is judged on the second
    snap = amt.update(dump2)
    assert snap["cvd_slope"] >= 0.2
    ctx = Context(symbol="X", bar=dump2, tick=0.05, vah=snap["vah"], val=snap["val"], poc=snap["poc"], cvd_slope=snap["cvd_slope"], extra=snap["extra"])
    assert detect(ctx) == ("VA_FADE", "LONG")
