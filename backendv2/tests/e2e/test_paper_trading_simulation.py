"""Paper trading execution and risk behavior with real runtime components."""

from __future__ import annotations

from app.domain.trading.model.aggregates import Portfolio
from app.domain.trading.model.entities import Signal as DomainSignal
from app.domain.trading.model.enums import SetupType, SignalType, Source
from app.domain.trading.service.risk_manager import RiskManager
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.runtime.pipeline.broker_sync import BrokerSynchronization
from app.runtime.pipeline.events import Signal
from app.runtime.pipeline.execution import ExecutionPipeline
from app.runtime.pipeline.position import PositionLifecycle


def test_signal_to_order_to_fill_to_position_to_exit_cycle() -> None:
    position = PositionLifecycle()
    execution = ExecutionPipeline(PaperBrokerAdapter())
    broker_sync = BrokerSynchronization()

    signal = Signal(
        symbol="CRUDEOIL",
        timestamp=1_714_982_100_000_000_000,
        type="LONG",
        entry=7253.0,
        sl=7200.0,
        tp=7359.0,
        rr=2.0,
        confidence=0.91,
        reason="paper execution e2e",
    )

    opened = position.process(signal)
    assert len(opened) == 1
    assert opened[0].event_type == "OPENED"

    order_statuses = execution.process(opened[0])
    assert len(order_statuses) == 1
    assert order_statuses[0].status == "FILLED"
    assert order_statuses[0].filled_quantity == opened[0].size

    fills = broker_sync.process(order_statuses[0])
    assert len(fills) == 1
    assert fills[0].price == opened[0].entry_price

def test_daily_loss_limit_halts_new_entries() -> None:
    risk = RiskManager()
    portfolio = Portfolio.create_default()
    risk._daily.reset(float(portfolio.equity))

    for _ in range(RiskManager.MAX_CONSECUTIVE_LOSSES):
        risk.record_trade_result(-1000.0)

    signal = DomainSignal.create(
        type=SignalType.BUY,
        price=7253.0,
        reason="loss-limit check",
        stop_loss=7200.0,
        take_profit=7359.0,
        timestamp="2026-05-07T09:30:00+05:30",
        setup=SetupType.TREND_MODEL,
        source=Source.AMT,
        metadata={"symbol": "CRUDEOIL"},
    )
    approved, reason = risk.check_signal(signal, portfolio)
    assert not approved
    assert "Consecutive losses" in reason

