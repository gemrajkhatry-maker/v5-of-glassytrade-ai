from quantv2.profile import VolumeProfile


def test_va_contiguous_and_lvn():
    p = VolumeProfile(tick=1.0)
    for _ in range(5):
        p.on_price_volume(100.0, 10.0)
        p.on_price_volume(104.0, 10.0)
    for _ in range(2):
        p.on_price_volume(102.0, 4.0)      # the LVN shelf between two masses
    assert p.poc == 100.0
    assert p.val == 100.0 and p.vah == 104.0     # 68.2% of 108 mass → both shelves included
    lvns = p.lvns(min_ratio=0.3)
    assert any(lo <= 102.0 <= hi for lo, hi in lvns)


def test_empty_profile_defaults():
    p = VolumeProfile(tick=0.5)
    assert p.poc == 0.0 and p.vah == 0.0 and p.val == 0.0
    assert p.lvns() == []
    assert p.layer() is None


def test_poc_tie_lowest_price_wins():
    p = VolumeProfile(tick=1.0)
    p.on_price_volume(105.0, 10.0)
    p.on_price_volume(101.0, 10.0)
    assert p.poc == 101.0


def test_va_is_contiguous_not_greedy():
    p = VolumeProfile(tick=1.0)
    p.on_price_volume(100.0, 60.0)
    p.on_price_volume(101.0, 30.0)
    p.on_price_volume(103.0, 20.0)  # empty bin 102 must be spanned, not skipped
    assert p.poc == 100.0
    assert p.val == 100.0
    assert p.vah == 102.0  # greedy-by-volume would stop VAH at 101


def test_va_gap_guard_stops_at_desert():
    p = VolumeProfile(tick=1.0)
    p.on_price_volume(100.0, 50.0)
    p.on_price_volume(103.0, 40.0)  # zero pair 101-102 < 1% of POC bin
    assert p.val == 100.0
    assert p.vah == 100.0


def test_lvn_ratio_and_min_width():
    p = VolumeProfile(tick=1.0)
    for _ in range(3):
        p.on_price_volume(100.0, 10.0)
        p.on_price_volume(104.0, 10.0)
    p.on_price_volume(102.0, 5.0)
    assert p.lvns(min_ratio=0.1) == [(101.0, 101.0), (103.0, 103.0)]  # 5 >= 0.1*30
    assert p.lvns(min_ratio=0.3) == [(101.0, 103.0)]  # 5 < 0.3*30 → trough merges
    assert p.lvns(min_ratio=0.3, min_width=4) == []


def test_layer_tag_passthrough():
    p = VolumeProfile(tick=1.0)
    p.on_price_volume(100.0, 1.0)
    assert p.layer() is None
    assert p.layer("session:open") == "session:open"
    assert p.layer() == "session:open"
