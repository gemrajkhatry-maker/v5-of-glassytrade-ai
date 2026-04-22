"""LLM session calendar uses tradable venue (MCX option under NSE default_exchange)."""

from unittest.mock import MagicMock

from app.application.handlers.llm_entry_handler import LLMEntryHandler


def test_session_market_mcx_commodity_overrides_nse_handler_exchange():
    gen = MagicMock()
    gen.is_ready.return_value = True
    handler = LLMEntryHandler(gen_ai_service=gen, exchange="NSE")
    assert handler.session_market_for_symbol("CRUDEOIL 14 MAY 8850 CALL") == "MCX"
    assert handler.session_market_for_symbol("GOLD 20 APR 70000 CE") == "MCX"


def test_session_market_nifty_uses_nse_when_handler_nfo():
    gen = MagicMock()
    gen.is_ready.return_value = True
    handler = LLMEntryHandler(gen_ai_service=gen, exchange="NFO")
    assert handler.session_market_for_symbol("NIFTY 27 MAR 23000 CE") == "NSE"
