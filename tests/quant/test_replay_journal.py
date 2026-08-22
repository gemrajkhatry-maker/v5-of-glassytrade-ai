"""L1 tests: journal replay integrity checks."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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
