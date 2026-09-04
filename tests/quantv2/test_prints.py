"""Doc-pinned tests for bubble print tracker — AMT §7.1 (bubbles ≥30 lots, institutional ≥100 or flag)."""

from quantv2.orderflow.prints import PrintTracker


def test_bubble_thresholds_per_doc():
    t = PrintTracker(min_bubble_qty=30.0, institutional_qty=100.0)
    assert t.on_print(1.0, 100.0, 29.0, "BUY") is None          # below 30: not a bubble
    b1 = t.on_print(2.0, 100.0, 30.0, "BUY")
    assert b1 is not None and b1.institutional is False          # 30–99: bubble, not institutional
    b2 = t.on_print(3.0, 100.5, 100.0, "SELL")
    assert b2.institutional is True
    near = t.bubbles_near(100.2, ticks=2, tick=0.05)             # ±2 ticks of 100.2 → [100.0, 100.1..100.3]
    assert len(near) == 2


def test_institutional_when_flagged_below_qty():
    t = PrintTracker(min_bubble_qty=30.0, institutional_qty=100.0)
    b = t.on_print(1.0, 200.0, 50.0, "BUY", flag=True)
    assert b is not None and b.institutional is True
    assert b.qty == 50.0


def test_sub_bubble_prints_not_tracked():
    t = PrintTracker(min_bubble_qty=30.0, institutional_qty=100.0)
    t.on_print(1.0, 100.0, 29.0, "BUY")
    assert t.bubbles_near(100.0, ticks=5, tick=0.05) == []
