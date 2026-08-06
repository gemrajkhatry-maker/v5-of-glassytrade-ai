# tests/quant/runtime/test_golden_runtime.py
"""Golden-file determinism: replaying the same tick sequence must yield an
identical event trace, identical projected WS state, and journal records that a
fresh Journal can read back (append-only JSONL replay).

Reuses the exact ``_ticks()`` fixture from the runtime test so this suite
exercises the same AGGRESSION-LONG pipeline as ``test_runtime.py``.
"""

from quant.brokers.synthetic import SyntheticGateway
from quant.persistence import Journal
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from tests.quant.runtime.test_runtime import _ticks


def _engine():
    return QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)


def test_engine_replay_is_identical():
    t1 = _engine().run()
    t2 = _engine().run()
    assert t1 == t2


def test_projected_state_deterministic():
    e1 = _engine()
    e2 = _engine()
    e1.run()
    e2.run()
    assert view_state_to_ws(e1.projector.snapshot("SYM")) == \
        view_state_to_ws(e2.projector.snapshot("SYM"))


def test_journal_writes_and_replays(tmp_path):
    path = str(tmp_path / "journal.jsonl")
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1,
                      journal_path=path)
    trace = eng.run()

    rows = Journal(path).replay()
    assert len(rows) == len(trace) == len(Journal(path))
    assert rows[0]["type"] == trace[0].__class__.__name__
    assert rows[-1]["type"] == trace[-1].__class__.__name__
    assert rows[0]["symbol"] == "SYM"
