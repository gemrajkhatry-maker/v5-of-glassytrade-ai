"""L1 tests: journal replay integrity checks."""

import importlib.util
import json
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_spec = importlib.util.spec_from_file_location(
    "_replay_journal", Path(__file__).resolve().parent / "replay_journal.py"
)
rj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rj)


def _write_journal(tmp_path, records):
    p = tmp_path / "j.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records))
    return str(p)


def test_clean_journal_zero_divergence(tmp_path, capsys):
    records = [
        {"type": "BarClosed", "time": "t1", "event_id": "1"},
        {"type": "DecisionProduced", "time": "t1", "event_id": "2",
         "decision": {"approved": True, "reason": "Triple-A", "signal": {"type": "LONG", "entry": 100.0}}},
        {"type": "PositionOpened", "time": "t1", "event_id": "3"},
        {"type": "PositionClosed", "time": "t2", "event_id": "4"},
    ]
    p = _write_journal(tmp_path, records)
    assert rj.main([sys.argv[0], p]) == 0
    assert "ZERO DIVERGENCE" in capsys.readouterr().out


def test_fill_without_approved_decision_flags(tmp_path, capsys):
    records = [
        {"type": "BarClosed", "time": "t1", "event_id": "1"},
        # No approved decision — fill appears from nowhere.
        {"type": "PositionOpened", "time": "t1", "event_id": "2"},
    ]
    p = _write_journal(tmp_path, records)
    assert rj.main([sys.argv[0], p]) == 1
    assert "without a preceding approved decision" in capsys.readouterr().out


def test_event_ordering_violation_flags(tmp_path, capsys):
    records = [
        {"type": "BarClosed", "time": "t1", "event_id": "5"},
        {"type": "BarClosed", "time": "t2", "event_id": "3"},  # went backwards
    ]
    p = _write_journal(tmp_path, records)
    assert rj.main([sys.argv[0], p]) == 1
    assert "ordering violation" in capsys.readouterr().out


def test_duplicate_event_ids_flag(tmp_path, capsys):
    records = [
        {"type": "BarClosed", "time": "t1", "event_id": "1"},
        {"type": "BarClosed", "time": "t2", "event_id": "1"},  # dupe
    ]
    p = _write_journal(tmp_path, records)
    assert rj.main([sys.argv[0], p]) == 1
    assert "duplicate event_ids" in capsys.readouterr().out


def test_engine_attach_journal_captures_events(tmp_path):
    """L1 enabler: coordinator attaches a per-day journal; the journal must
    capture BarClosed + DecisionProduced events from a live run."""
    from quant.brokers.gateway import Tick
    from quant.runtime import QuantEngine

    jpath = tmp_path / "day_SYM.jsonl"

    class GW:
        def __init__(self):
            self._t = [Tick(str(i * 61), 100.0, 10, 5, 5) for i in range(4)]

        def subscribe(self, s):
            pass

        def next_tick(self):
            return self._t.pop(0) if self._t else None

        def try_next_tick(self):
            return self.next_tick()

    eng = QuantEngine(GW(), "TEST CALL", interval_seconds=60)
    eng.attach_journal(str(jpath))
    assert eng._journal is not None, "attach_journal did not create journal"

    eng.run(max_steps=10)

    rows = [json.loads(lv) for lv in jpath.read_text().splitlines() if lv.strip()]
    types = {r["type"] for r in rows}
    assert "BarClosed" in types, f"journal missing bars: {types}"
    assert any(r["type"] == "DecisionProduced" for r in rows)


def test_attach_journal_is_idempotent(tmp_path):
    from quant.runtime import QuantEngine

    class GW:
        def subscribe(self, s):
            pass

        def next_tick(self):
            return None

        def try_next_tick(self):
            return None

    eng = QuantEngine(GW(), "S", interval_seconds=60)
    p1 = str(tmp_path / "a.jsonl")
    p2 = str(tmp_path / "b.jsonl")
    eng.attach_journal(p1)
    eng.attach_journal(p2)  # second attach must be a no-op
    assert eng._journal._path == p1, "second attach replaced the journal"
