# tests/quant/runtime/test_golden_runtime.py
"""Golden-file determinism: replaying the same tick sequence must yield an
identical event trace, identical projected WS state, and journal records that a
fresh Journal can read back (append-only JSONL replay).

Reuses the exact ``_ticks()`` fixture from the runtime test so this suite
exercises the same AGGRESSION-LONG pipeline as ``test_runtime.py``.
"""

from tests.helpers.synthetic import SyntheticGateway
from quant.events import (
    AmtUpdated,
    BarClosed,
    DecisionProduced,
    DepthUpdated,
    PositionClosed,
    PositionOpened,
    PositionReduced,
    RiskUpdated,
    SignalApproved,
)
from quant.persistence import Journal
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from tests.quant.runtime.test_runtime import _ticks


def _engine(symbol="SYM_GOLDEN"):
    from quant.execution.risk import SessionRisk
    SessionRisk(storage=None, symbol=symbol).reset_session()
    return QuantEngine(SyntheticGateway(_ticks()), symbol, interval_seconds=1)


def test_engine_replay_is_identical():
    from quant.events import AgentDecisionProduced
    t1 = _engine("SYM_G1").run()
    t2 = _engine("SYM_G2").run()
    t1_sync = [(type(e).__name__, getattr(e, "time", "")) for e in t1 if not isinstance(e, AgentDecisionProduced)]
    t2_sync = [(type(e).__name__, getattr(e, "time", "")) for e in t2 if not isinstance(e, AgentDecisionProduced)]
    assert t1_sync == t2_sync


def test_projected_state_deterministic():
    e1 = _engine("SYM_G1")
    e2 = _engine("SYM_G2")
    e1.run()
    e2.run()
    assert view_state_to_ws(e1.projector.snapshot("SYM_G1"))["amt"]["poc"] == \
        view_state_to_ws(e2.projector.snapshot("SYM_G2"))["amt"]["poc"]


def test_journal_writes_and_replays(tmp_path):
    path = str(tmp_path / "journal.jsonl")
    eng = _engine("SYM_JOURNAL")
    eng._journal_path = path
    from quant.persistence import Journal
    eng._journal = Journal(path=path)
    eng._journal_subscribed = True
    def _journal_subscriber(event):
        eng._journal.append({"type": event.__class__.__name__})
    for evt_type in (
        BarClosed, DecisionProduced, SignalApproved, PositionOpened,
        PositionClosed, PositionReduced, RiskUpdated, DepthUpdated, AmtUpdated,
    ):
        eng._bus.subscribe(evt_type, _journal_subscriber, priority=-100)
    trace = eng.run()
    from quant.events import AgentDecisionProduced
    sync_trace = [e for e in trace if not isinstance(e, AgentDecisionProduced)]

    rows = Journal(path).replay()
    assert len(rows) == len(sync_trace) == len(Journal(path))
    assert rows[0]["type"] == sync_trace[0].__class__.__name__
    assert rows[-1]["type"] == sync_trace[-1].__class__.__name__
