"""Runtime risk-position execution threading regression checks."""

from app.runtime.pipeline.events import FillEvent, Signal, PositionEvent
from app.runtime.pipeline.position import PositionLifecycle
from app.runtime.pipeline.risk import RiskEvaluation


def test_fill_generates_closed_position_event() -> None:
    lifecycle = PositionLifecycle()
    signal = Signal(
        symbol="BANKNIFTY",
        timestamp=1.0,
        type="LONG",
        entry=45000.0,
        sl=44900.0,
        tp=45100.0,
        rr=2.0,
        confidence=0.8,
        reason="test",
    )
    open_events = lifecycle.process(signal)
    assert len(open_events) == 1
    open_event = open_events[0]
    assert open_event.event_type == "OPENED"

    fill = FillEvent(
        order_id=open_event.position_id,
        symbol=signal.symbol,
        side="BUY",
        quantity=open_event.size,
        price=open_event.entry_price,
        timestamp=2.0,
    )
    close_events = lifecycle.process(fill)
    assert len(close_events) == 1
    assert close_events[0].event_type == "CLOSED"
    assert close_events[0].position_id == open_event.position_id


def test_risk_sync_position_events_updates_portfolio_and_trades() -> None:
    risk = RiskEvaluation()
    lifecycle = PositionLifecycle()

    signal = Signal(
        symbol="BANKNIFTY",
        timestamp=1.0,
        type="LONG",
        entry=45100.0,
        sl=45000.0,
        tp=45300.0,
        rr=1.6,
        confidence=0.9,
        reason="test",
    )
    open_events = lifecycle.process(signal)
    open_event = open_events[0]
    risk.sync_position_event(open_event)

    state = risk._state_for("BANKNIFTY")
    assert len(state.portfolio.positions) == 1

    close_event = PositionEvent(
        symbol="BANKNIFTY",
        timestamp=2.0,
        event_type="CLOSED",
        position_id=open_event.position_id,
        entry_price=open_event.entry_price,
        size=open_event.size,
        side=open_event.side,
        stop_loss=open_event.stop_loss,
        take_profit=open_event.take_profit,
        pnl=120.0,
        exit_reason="FILLED",
    )
    risk.sync_position_event(close_event)

    state = risk._state_for("BANKNIFTY")
    assert len(state.portfolio.positions) == 0
    assert state.risk_manager._daily.total_trades == 1
    assert state.risk_manager._daily.realized_pnl == 120.0
