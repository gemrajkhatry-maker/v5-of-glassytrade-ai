from quantv2.second_drive import SecondDrive
from quantv2.types import Bar


def test_reclaim_continuation():
    sd = SecondDrive(max_drives=3)
    lvl = 100.0
    assert sd.on_bar(Bar(time="1", open=100.0, high=100.9, low=99.9, close=100.1, volume=10.0), lvl) is None       # probe+reject
    r = sd.on_bar(Bar(time="2", open=100.1, high=100.5, low=100.0, close=100.6, volume=12.0), lvl)                  # reclaim above
    assert r and r["reclaimed"] is True and r["direction"] == "LONG" and r["drive_number"] == 1
    # repeated drives stop after max
    for i in range(4):
        sd.on_bar(Bar(time=f"3{i}", open=100.0, high=100.9, low=99.9, close=100.1, volume=10.0), lvl)
        sd.on_bar(Bar(time=f"4{i}", open=100.1, high=100.5, low=100.0, close=100.6, volume=12.0), lvl)
    assert sd.drives >= 3 and sd.active is False


def test_reclaim_short():
    sd = SecondDrive()
    lvl = 200.0
    assert sd.on_bar(Bar(time="1", open=200.0, high=200.1, low=199.1, close=199.9, volume=10.0), lvl) is None  # probe below+reject
    r = sd.on_bar(Bar(time="2", open=199.9, high=200.0, low=199.4, close=199.4, volume=12.0), lvl)             # reclaim below
    assert r and r["reclaimed"] is True and r["direction"] == "SHORT" and r["drive_number"] == 1


def test_no_probe_no_signal():
    sd = SecondDrive()
    lvl = 100.0
    # price accepts above the level with no rejected probe — nothing to reclaim
    assert sd.on_bar(Bar(time="1", open=100.05, high=100.3, low=100.02, close=100.2, volume=10.0), lvl) is None
    assert sd.on_bar(Bar(time="2", open=100.2, high=100.4, low=100.05, close=100.35, volume=10.0), lvl) is None
    assert sd.drives == 0 and sd.active is True
