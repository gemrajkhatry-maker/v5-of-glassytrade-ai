from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.application.services.trading_session import TradingSessionService
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from quant.contracts.ports.probability_inference import NoOpProbabilityAdapter
from quant.contracts.value_objects import OHLC


class _GenAI:
    def is_ready(self) -> bool:
        return False


def test_amt_failure_blocks_entry_and_overseer_paths(monkeypatch):
    service = TradingSessionService(
        broker=PaperBrokerAdapter(),
        gen_ai_service=_GenAI(),
        probability_engine=NoOpProbabilityAdapter(),
        allow_short=False,
    )
    symbol = "CRUDEOIL 17 AUG 7200 CALL"
    session = service.get_or_create_session(symbol)
    session.portfolio.has_open_positions = Mock(return_value=False)

    service._amt_service.run_analysis = Mock(return_value=None)
    service._event_router.run_micro_agent_pipeline = Mock()
    service._event_router.run_overseer_if_needed = Mock()
    service._event_router.execute_entry_path = Mock()
    service._lifecycle_handler.check_exits = Mock(return_value=False)

    try:
        service.process_tick(
            symbol,
            OHLC.create("2026-08-07T09:15:00Z", 100, 101, 99, 100, 100),
        )
    finally:
        service.cleanup()

    service._event_router.run_micro_agent_pipeline.assert_not_called()
    service._event_router.run_overseer_if_needed.assert_not_called()
    service._event_router.execute_entry_path.assert_called_once()
    assert service._event_router.execute_entry_path.call_args.args[5] is False
    service._lifecycle_handler.check_exits.assert_called_once()
