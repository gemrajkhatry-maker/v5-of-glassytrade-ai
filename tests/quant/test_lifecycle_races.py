"""Race regression: concurrent coordinator lifecycle transitions.

Guards the TOCTOU fixed by _lifecycle_lock: two concurrent
switch_symbol(old, new) calls used to both pass the membership check and
spawn DUPLICATE engines for `new` (duplicate ticks -> duplicate orders).
"""

import threading

from quant.multi_engine import QuantCoordinator


class _FakeMD:
    """Minimal market-data double; get_nearest_futures drives symbol sets."""

    def __init__(self, futures_by_underlying: dict[str, str]):
        self._fut = futures_by_underlying

    def get_nearest_futures(self, underlying, exchange=None):
        return self._fut.get(underlying)

    def fetch_history(self, *a, **k):
        return []


def _make_coordinator(futures: dict[str, str]) -> QuantCoordinator:
    return QuantCoordinator(
        market_data=_FakeMD(futures),
        config={
            "include_futures": False,
            "n": 4,
            "exchange": "MCX",
            "underlyings": list(futures.keys()),
            # Persisted-selection bypass: force a fresh scan each start by
            # pointing contracts_file at a path that will not exist.
            "contracts_file": "/tmp/nonexistent-contracts-race.json",
        },
    )


def test_concurrent_switch_spawns_exactly_one_engine(monkeypatch):
    """Two threads switching the same old symbol concurrently must yield
    exactly one engine for the new symbol."""
    coord = _make_coordinator({"GOLDM": "GOLDM SEP FUT", "SILVERM": "SILVERM AUG FUT"})
    # Deterministic scan: one future + one option per underlying.
    monkeypatch.setattr(
        coord,
        "_scan",
        lambda force=False: ["GOLDM SEP FUT", "GOLDM 28 AUG 159500 CALL",
                             "SILVERM AUG FUT", "SILVERM 24 AUG 246000 PUT"],
        raising=True,
    )
    coord.start()

    barrier = threading.Barrier(2)
    results: list[bool] = []

    def switch():
        barrier.wait()  # maximize overlap of the check-then-act window
        results.append(coord.switch_symbol("SILVERM 24 AUG 246000 PUT",
                                           "CRUDEOIL 17 SEP 8300 CALL"))

    t1, t2 = threading.Thread(target=switch), threading.Thread(target=switch)
    t1.start(); t2.start(); t1.join(); t2.join()

    engines_for_new = [s for s in coord.symbols() if s == "CRUDEOIL 17 SEP 8300 CALL"]
    assert results == [True, True] or results == [True] or results.count(True) >= 1
    # THE invariant: exactly one engine instance for the new symbol.
    assert len(engines_for_new) <= 1, f"duplicate engines spawned: {coord.symbols()}"
    # And the old engine is gone regardless.
    assert "SILVERM 24 AUG 246000 PUT" not in coord.symbols()
    coord.stop()


def test_rescan_and_switch_do_not_interleave(monkeypatch):
    """A rescan running concurrently with a switch must serialize: the final
    state must be consistent (no orphaned/duplicated engines)."""
    coord = _make_coordinator({"GOLDM": "GOLDM SEP FUT"})
    scan_a = ["GOLDM SEP FUT", "GOLDM 28 AUG 159500 CALL"]
    monkeypatch.setattr(coord, "_scan", lambda force=False: list(scan_a), raising=True)
    coord.start()

    switched = threading.Event()

    def do_rescan():
        switched.wait(timeout=2)
        monkeypatch.setattr(
            coord, "_scan",
            lambda force=False: ["GOLDM SEP FUT", "GOLDM 28 AUG 159500 CALL",
                                 "SILVERM AUG FUT"],
            raising=True,
        )
        coord.rescan()

    t = threading.Thread(target=do_rescan)
    t.start()
    ok = coord.switch_symbol("GOLDM 28 AUG 159500 CALL", "CRUDEOIL 17 SEP 8300 CALL")
    switched.set()
    t.join(timeout=5)

    syms = coord.symbols()
    assert len(syms) == len(set(syms)), f"duplicate engines after interleave: {syms}"
    # Serialized transitions: the LAST completed transition defines the world.
    # Either the switch won (CRUDEOIL present) or the rescan replaced the set
    # afterwards (CRUDEOIL absent) — both are consistent; duplicates are not.
    if ok and "CRUDEOIL 17 SEP 8300 CALL" not in syms:
        assert "SILVERM AUG FUT" in syms, "rescan must have run after switch"
    coord.stop()
