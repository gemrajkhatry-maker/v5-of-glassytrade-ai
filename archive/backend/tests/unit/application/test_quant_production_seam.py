from __future__ import annotations

from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

from app.application.services.trading_session import TradingSessionService


def test_evaluate_quant_decision_passes_selected_bar_and_fact_snapshot() -> None:
    service = TradingSessionService.__new__(TradingSessionService)
    service._amt_service = Mock()
    service._quant_bridge = Mock()
    service._quant_bridge.on_bar_close_with_decision.return_value = {
        "time": "bar-1",
        "tripleAPhase": "AGGRESSION",
    }

    bar = SimpleNamespace(time="bar-1")
    cache = Mock()
    session = SimpleNamespace()
    event = SimpleNamespace(symbol="SYM")
    facts = {
        "position_open": False,
        "agent_direction": "LONG",
        "agent_probability": 0.7,
    }

    service._evaluate_quant_decision(event, session, cache, bar=bar, facts=facts)

    service._quant_bridge.on_bar_close_with_decision.assert_called_once_with(
        "SYM", bar, session, facts
    )
    cache.update_auction.assert_called_once_with(
        {"time": "bar-1", "tripleAPhase": "AGGRESSION"}
    )


def test_evaluate_quant_decision_does_not_feed_when_no_bar() -> None:
    service = TradingSessionService.__new__(TradingSessionService)
    service._quant_bridge = Mock()
    cache = Mock()
    session = SimpleNamespace(_lock=RLock(), last_quant_decision={"approved": True})

    service._evaluate_quant_decision(
        SimpleNamespace(symbol="SYM"),
        session,
        cache,
        bar=None,
        facts={},
    )

    service._quant_bridge.on_bar_close_with_decision.assert_not_called()
    cache.update_auction.assert_not_called()
