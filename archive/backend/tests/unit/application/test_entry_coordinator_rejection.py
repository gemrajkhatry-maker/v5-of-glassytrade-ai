from __future__ import annotations

from unittest.mock import Mock

from app.application.services.entry_coordinator import EntryCoordinator
from app.application.services.session_state_manager import SessionState
from quant.contracts.entities import Signal
from quant.contracts.enums import SetupType, SignalType, Source


def test_broker_rejection_does_not_persist_or_raise():
    broker = Mock()
    broker.execute_order.return_value = None
    storage = Mock()
    risk = Mock()
    risk.validate_entry.return_value = True
    option_selector = Mock()
    option_selector.select_strike.return_value = 100
    option_selector._lot_size_for.return_value = 1

    coordinator = EntryCoordinator(
        broker=broker,
        lifecycle_handler=Mock(),
        event_logger=Mock(),
        storage=storage,
        risk_coordinator=risk,
        option_selector=option_selector,
        state_manager=Mock(),
    )
    signal = Signal.create(
        type=SignalType.BUY,
        price=100,
        reason="test",
        stop_loss=95,
        take_profit=110,
        timestamp="2026-08-07T09:15:00Z",
        setup=SetupType.TREND_MODEL,
        source=Source.LLM,
        metadata={
            "trade_thesis": {
                "market_state": "BALANCED",
                "location_type": "UPPER",
                "location_level": 1,
                "aggression_trigger": "test",
                "session_context": "MORNING",
                "invalidation_level": 95,
                "setup_family": "trend_model",
            }
        },
    )

    coordinator.execute_signal("SYM", signal, SessionState(symbol="SYM"))

    broker.execute_order.assert_called_once()
    storage.save_open_position.assert_not_called()
    assert coordinator._db_fallback.buffer_size == 0
