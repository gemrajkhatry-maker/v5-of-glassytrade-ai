"""Stage boundary tests from ownership contract.

These tests pin snapshot-diff expectations for stage-local mutations on a runtime tick
and on the rejection rollback path.
"""

from app.runtime.pipeline.events import Signal
from app.runtime.pipeline.events import (
    GateResult,
    FillEvent,
    OrderStatusEvent,
    PositionEvent,
    Tick,
)
from app.runtime.pipeline.events import GateResultType
from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator.session import SessionRuntime


def _changed_sections(before: dict, after: dict) -> set[str]:
    all_keys = set(before) | set(after)
    return {key for key in all_keys if before.get(key) != after.get(key)}


def _snapshot_stage(stage: object) -> dict:
    snapshot = getattr(stage, "snapshot", None)
    if callable(snapshot):
        payload = snapshot()
        return payload if isinstance(payload, dict) else {}
    return {}


def _runtime_snapshot(runtime: SessionRuntime) -> dict:
    return {
        "_event_count": runtime._event_count,
        "sequencer": runtime._sequencer.snapshot(),
        "normalizer": runtime._normalizer.snapshot(),
        "candles": _snapshot_stage(runtime._candles),
        "orderflow": _snapshot_stage(runtime._orderflow),
        "microstructure": _snapshot_stage(runtime._microstructure),
        "features": _snapshot_stage(runtime._features),
        "market_structure": _snapshot_stage(runtime._market_structure),
        "signal": _snapshot_stage(runtime._signal),
        "gates": _snapshot_stage(runtime._gates),
        "risk": _snapshot_stage(runtime._risk),
        "telemetry": runtime._telemetry.snapshot(),
        "position": _snapshot_stage(runtime._position),
        "persistence": _snapshot_stage(runtime._persistence),
        "broker_sync": _snapshot_stage(runtime._broker_sync),
        "execution": _snapshot_stage(runtime._execution),
        "strategy": _snapshot_stage(runtime._strategy),
    }


def _ticks() -> list[Tick]:
    return [
        Tick(
            symbol="BANKNIFTY",
            timestamp=float(i * 1_000_000_000),
            price=45000.0 + i * 0.5,
            volume=100.0,
            bid=44999.0 + i * 0.5,
            ask=45001.0 + i * 0.5,
            bid_volume=50.0,
            ask_volume=50.0,
        )
        for i in range(1)
    ]


def test_tick_snapshot_mutations_are_stage_local() -> None:
    runtime = SessionRuntime(
        feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=_ticks(), strict_symbol_mode=True),
        symbols=["BANKNIFTY"],
    )

    before = _runtime_snapshot(runtime)
    runtime._process_tick(_ticks()[0])
    after = _runtime_snapshot(runtime)

    changed = _changed_sections(before, after)
    assert changed == {
        "_event_count",
        "sequencer",
        "normalizer",
        "candles",
        "orderflow",
        "microstructure",
        "features",
        "signal",
        "persistence",
        "telemetry",
    }


class _FailingBroker:
    async def place_order(self, symbol: str, side: str, quantity: float, price: float):
        raise RuntimeError(f"broker rejected {symbol}:{side}")


def _make_rejected_signal() -> Signal:
    return Signal(
        symbol="BANKNIFTY",
        timestamp=1_000_000_000,
        type="LONG",
        entry=45010.0,
        sl=44900.0,
        tp=45200.0,
        rr=2.0,
        confidence=0.92,
        reason="rejected path unit guard",
    )


def test_rejected_signal_flow_mutates_only_rollback_contract_sections() -> None:
    runtime = SessionRuntime(
        feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=[], strict_symbol_mode=True),
        symbols=["BANKNIFTY"],
    )
    runtime._execution._broker = _FailingBroker()

    before = _runtime_snapshot(runtime)
    stage_events: list[object] = []
    runtime._run_signal_flow(_make_rejected_signal(), stage_events)
    after = _runtime_snapshot(runtime)

    changed = _changed_sections(before, after)
    assert "position" in changed
    assert "risk" in changed
    assert changed.issubset({"position", "risk", "gates"})

    fills = [event for event in stage_events if isinstance(event, FillEvent)]
    order_status = [
        event for event in stage_events
        if isinstance(event, OrderStatusEvent) and event.symbol == "BANKNIFTY"
    ]
    closed = [
        event for event in stage_events
        if isinstance(event, PositionEvent) and event.event_type == "CLOSED"
    ]
    assert order_status and order_status[0].status == "REJECTED"
    assert fills == []
    assert closed == []

    runtime_portfolio = runtime._position.get_portfolio("BANKNIFTY")
    assert not runtime_portfolio.has_open_positions()
    risk_snapshot = runtime._risk.snapshot()
    assert risk_snapshot["BANKNIFTY"]["portfolio"]["open_positions"] == []


def test_risk_state_is_seeded_from_portfolio_before_first_signal() -> None:
    runtime = SessionRuntime(
        feed=type("Feed", (), {"start": lambda self: None, "stop": lambda self: None, "stream": lambda self: iter([]), "name": lambda self: "noop", "symbols": lambda self: ["BANKNIFTY"]})(),  # noqa: E501
        symbols=["BANKNIFTY"],
    )
    gate = GateResult(
        symbol="BANKNIFTY",
        timestamp=1.0,
        signal=Signal(
            symbol="BANKNIFTY",
            timestamp=1.0,
            type="LONG",
            entry=45000.0,
            sl=44800.0,
            tp=45200.0,
            rr=2.0,
            confidence=0.9,
            reason="risk baseline",
        ),
        result=GateResultType.APPROVED,
    )
    risk_results = runtime._risk.process(gate)
    assert risk_results and risk_results[0].approved
    snapshot = runtime._risk.snapshot()
    daily = snapshot["BANKNIFTY"]["risk_manager"]["daily"]
    assert daily["starting_equity"] == 1000000
    assert daily["current_equity"] == 1000000
