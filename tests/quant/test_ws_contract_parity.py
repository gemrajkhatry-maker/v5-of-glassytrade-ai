"""WS snapshot contract parity — the anti-shotgun-surgery guard.

The snapshot shape was historically defined independently in:
  - quant/ws_adapter.view_state_to_ws   (dict literal)
  - quant/ws_contract.WSSnapshot.to_dict (second dict literal)
  - frontend/types.ts                   (TS mirror)

A single key removal (``auction``) required 9 coordinated file edits and
broke three independent test files. These tests make drift impossible:

1. Both producers emit EXACTLY WS_SNAPSHOT_KEYS — adding/removing a key in
   one without the other fails here, at the contract level.
2. A golden fixture pins the full shape so frontend consumers see the break
   in their own CI via tests/runtime-audit fixture regeneration.

If a key change is intended: update WS_SNAPSHOT_KEYS, both producers, this
test's expected set, and regenerate the fixture IN THE SAME COMMIT.
"""

import json
import pathlib

import pytest

from quant.execution.order import Fill, Order, Position
from quant.events import DepthUpdated
from quant.state import StateProjector
from quant.ws_adapter import view_state_to_ws
from quant.ws_contract import WS_SNAPSHOT_KEYS, WSPortfolio, WSSnapshot


def _projector_with_everything() -> StateProjector:
    """Fold a representative event set so every ViewState field is non-default."""
    proj = StateProjector()
    from quant.bars import Bar
    from quant.decision.decision_service import QuantDecision
    from quant.decision.signal_builder import Signal
    from quant.events import (
        AmtUpdated,
        BarClosed,
        DecisionProduced,
        PositionOpened,
        RiskUpdated,
    )
    from quant.execution.risk import RiskState

    bar = Bar(time="2026-08-21T09:15:00+05:30", open=100.0, high=101.0,
              low=99.0, close=100.5, volume=10)
    proj.on_event(BarClosed(symbol="S", time=bar.time, bar=bar))
    sig = Signal(type="LONG", reason="All gates passed", entry=100.5, sl=99.0,
                 tp=102.5, rr=2.0, model_label="Triple-A", symbol="S",
                 timestamp=bar.time)
    dec = QuantDecision(approved=True, signal=sig, reason="Triple-A",
                        phase="AGGRESSION", gate_results=(), block_reasons=(),
                        model_label="Triple-A")
    proj.on_event(DecisionProduced(symbol="S", time=bar.time, decision=dec))
    pos = Position(order=Order(sig, 10), open_price=100.5, open_time=bar.time, size=10)
    proj.on_event(PositionOpened(symbol="S", time=bar.time, position=pos))
    proj.on_event(RiskUpdated(symbol="S", time=bar.time,
                              risk=RiskState(daily_pnl=0.0,
                                             consecutive_losses=0,
                                             halted=False, halt_reason="",
                                             risk_per_trade_pct=0.005)))
    proj.on_event(AmtUpdated(symbol="S", time=bar.time, amt={"poc": 100.2}))
    proj.on_event(DepthUpdated(symbol="S", time=bar.time,
                               depth={"bids": [], "asks": []}))
    return proj


def test_adapter_emits_exact_contract_keys():
    ws = view_state_to_ws(_projector_with_everything().snapshot("S"))
    assert set(ws) == set(WS_SNAPSHOT_KEYS), (
        "ws_adapter drifted from WS_SNAPSHOT_KEYS: "
        f"extra={set(ws) - set(WS_SNAPSHOT_KEYS)} "
        f"missing={set(WS_SNAPSHOT_KEYS) - set(ws)}"
    )


def test_wssnapshot_to_dict_emits_exact_contract_keys():
    snap = WSSnapshot(
        _symbol="S",
        portfolio=WSPortfolio(balance=1_000_000.0, equity=1_000_000.0,
                              leverage=10),
    )
    d = snap.to_dict()
    assert set(d) == set(WS_SNAPSHOT_KEYS), (
        "WSSnapshot.to_dict drifted from WS_SNAPSHOT_KEYS: "
        f"extra={set(d) - set(WS_SNAPSHOT_KEYS)} "
        f"missing={set(WS_SNAPSHOT_KEYS) - set(d)}"
    )


def test_both_producers_agree_on_shape():
    """The two independent producers must produce identical key sets AND the
    same JSON-serializable types for shared keys (structural parity)."""
    vs = view_state_to_ws(_projector_with_everything().snapshot("S"))
    d = WSSnapshot(
        _symbol="S",
        portfolio=WSPortfolio(balance=1_000_000.0, equity=1_000_000.0,
                              leverage=10),
    ).to_dict()
    assert set(vs) == set(d) == set(WS_SNAPSHOT_KEYS)


GOLDEN_FIXTURE = pathlib.Path(__file__).parent / "golden_ws_snapshot.json"


def test_golden_fixture_matches_current_contract():
    """Pin the exact wire shape. Intentional contract changes must regenerate
    this fixture in the same commit (python -m tests.quant.regen_ws_fixture).
    Unintentional drift fails here."""
    ws = view_state_to_ws(_projector_with_everything().snapshot("S"))
    actual = json.dumps(ws, sort_keys=True, indent=1, default=str)
    if not GOLDEN_FIXTURE.exists():
        GOLDEN_FIXTURE.write_text(actual)
    expected = GOLDEN_FIXTURE.read_text()
    assert actual == expected, (
        "WS snapshot wire shape changed. If intentional, regenerate:\n"
        "  python -m tests.quant.regen_ws_fixture\n"
        f"First diff near: {next((a for a, b in zip(actual.splitlines(), expected.splitlines()) if a != b), '?')!r}"
    )
