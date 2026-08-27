"""SessionLevelStore — prior-session POC/VAH/VAL persistence + NPOC port.

Phase 1: the engine persists each completed session's levels so the AMT
analyzer and the Triple-A take-profit can target the *previous balance area*
(Fabio's rule) instead of a bare 2R placeholder.
"""

from quant.amt.session.npoc import NPOCTracker
from quant.session_levels import SessionLevelStore


def test_levels_roundtrip_in_memory():
    store = SessionLevelStore()  # memory-only (tests / replay)
    assert store.load_levels("SYM")["poc"] == 0.0
    store.save_levels("SYM", "2026-08-10", 100.0, 102.0, 98.0)
    rec = store.load_levels("SYM")
    # r2 regression (gap-close persistence, 2c99117): save/load now emits an
    # additive "close" key; in-memory save without an explicit close persists
    # the default 0.0 and load_levels always returns all five fields.
    assert rec == {"date": "2026-08-10", "poc": 100.0, "vah": 102.0, "val": 98.0, "close": 0.0}


def test_levels_persist_across_instances(tmp_path):
    path = str(tmp_path / "levels.json")
    SessionLevelStore(path).save_levels("SYM", "2026-08-10", 100.0, 102.0, 98.0)
    reloaded = SessionLevelStore(path)
    assert reloaded.load_levels("SYM")["poc"] == 100.0
    assert reloaded.load_levels("SYM")["vah"] == 102.0


def test_levels_overwrite_same_symbol():
    store = SessionLevelStore()
    store.save_levels("SYM", "2026-08-10", 100.0, 102.0, 98.0)
    store.save_levels("SYM", "2026-08-11", 99.0, 101.0, 97.0)
    rec = store.load_levels("SYM")
    assert rec["date"] == "2026-08-11" and rec["poc"] == 99.0


def test_npoc_tracker_port_roundtrip(tmp_path):
    """NPOCTracker -> SessionLevelStore persists fills across instances."""
    path = str(tmp_path / "npoc.json")
    store = SessionLevelStore(path)
    tracker = NPOCTracker(storage_port=store)
    tracker.add_session_poc("NIFTY", "2026-08-10", 24500.0)

    # Price revisits the NPOC -> marked filled, removed from active.
    filled = tracker.check_and_fill("NIFTY", 24500.0, 1.0)
    assert filled == ["2026-08-10"]
    assert tracker.get_active_npocs("NIFTY", 24500.0).nearest_above is None

    # A fresh tracker over the same file sees the fill (no resurrection).
    tracker2 = NPOCTracker(storage_port=SessionLevelStore(path))
    tracker2.load_from_storage("NIFTY")
    assert tracker2.get_active_npocs("NIFTY", 24500.0).all_active == ()


def test_unfilled_npoc_survives_restart(tmp_path):
    """An unfilled prior-session POC is restored as an active magnet."""
    path = str(tmp_path / "npoc.json")
    SessionLevelStore(path).save_npoc("NIFTY", "2026-08-10", 24500.0)
    tracker = NPOCTracker(storage_port=SessionLevelStore(path))
    tracker.load_from_storage("NIFTY")
    res = tracker.get_active_npocs("NIFTY", 24000.0)
    assert res.nearest_above is not None
    assert res.nearest_above.price == 24500.0
    assert res.nearest_above.session_date == "2026-08-10"


def test_npoc_dedupe_same_session(tmp_path):
    path = str(tmp_path / "npoc.json")
    store = SessionLevelStore(path)
    store.save_npoc("NIFTY", "2026-08-10", 24500.0)
    store.save_npoc("NIFTY", "2026-08-10", 24501.0)  # duplicate session
    active = SessionLevelStore(path).get_active_npocs("NIFTY")
    assert len(active) == 1
    assert active[0]["poc_price"] == 24500.0
    assert active[0]["underlying"] == "NIFTY"
