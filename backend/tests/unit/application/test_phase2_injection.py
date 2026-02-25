"""Phase 2 tests — constructor injection for TradingSessionService."""
from unittest.mock import MagicMock, patch
from app.application.services.trading_session import TradingSessionService


class TestConstructorInjection:
    def test_default_construction(self):
        """Original constructor signature still works."""
        bus = MagicMock()
        broker = MagicMock()
        gen_ai = MagicMock()
        svc = TradingSessionService(bus, broker, gen_ai)
        assert svc._amt_handler is not None
        assert svc._lifecycle_handler is not None

    def test_custom_handler_injection(self):
        """Can inject custom handlers."""
        bus = MagicMock()
        broker = MagicMock()
        gen_ai = MagicMock()
        mock_amt = MagicMock()
        svc = TradingSessionService(bus, broker, gen_ai, amt_handler=mock_amt)
        assert svc._amt_handler is mock_amt
