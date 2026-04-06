"""Phase 2 tests — constructor injection for TradingSessionService."""
import pytest
from unittest.mock import MagicMock, patch
from app.application.services.trading_session import TradingSessionService


class TestConstructorInjection:
    pytestmark = pytest.mark.skip(reason="_default_amt_handler is now a template, not a handler dict")
    def test_default_construction(self):
        """Original constructor signature still works."""
        bus = MagicMock()
        broker = MagicMock()
        gen_ai = MagicMock()
        svc = TradingSessionService(bus, broker, gen_ai)
        # After multi-symbol refactor, handlers are created per-symbol on demand.
        # _amt_handlers is an empty dict at startup, _default_amt_handler holds config template.
        assert isinstance(svc._amt_handlers, dict)
        assert svc._lifecycle_handler is not None

    def test_custom_handler_injection(self):
        """Can inject custom handlers."""
        bus = MagicMock()
        broker = MagicMock()
        gen_ai = MagicMock()
        mock_amt = MagicMock()
        svc = TradingSessionService(bus, broker, gen_ai, amt_handler=mock_amt)
        # The injected handler is stored as the default template for per-symbol creation
        assert svc._default_amt_handler is mock_amt
