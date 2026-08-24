from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.application.services.amt_service import AMTService


def test_failed_analysis_clears_previous_source_bar() -> None:
    service = AMTService()
    service._latest_source_bars["SYM"] = SimpleNamespace(time="stale")
    service._amt_handlers["SYM"] = Mock()
    service._amt_handlers["SYM"].analyze.side_effect = RuntimeError("broken")

    cache = Mock()
    cache.has_underlying_data.return_value = False
    cache.get_option_data.return_value = [SimpleNamespace(time="current")]
    risk = Mock()
    risk.get_session_risk_manager.return_value = None
    event = SimpleNamespace(symbol="SYM", order_book=None, tick=None)

    assert service.run_analysis(event, SimpleNamespace(), cache, risk) is None
    assert service.latest_closed_bar(cache, "SYM") is None


def test_amt_source_is_pinned_until_explicit_reset() -> None:
    service = AMTService()
    option_bar = SimpleNamespace(time="option")
    futures_bar = SimpleNamespace(time="futures")
    cache = Mock()
    cache.get_option_data.return_value = [option_bar]
    cache.get_underlying_data.return_value = [futures_bar]
    cache.has_underlying_data.return_value = False

    data, source = service._select_amt_data_source(cache, 5, symbol="SYM")
    assert source == "option"
    assert data == [option_bar]

    # Futures warm-up must not silently change the auction source mid-session.
    cache.has_underlying_data.return_value = True
    data, source = service._select_amt_data_source(cache, 5, symbol="SYM")
    assert source == "option"
    assert data == [option_bar]

    service.reset("SYM")
    data, source = service._select_amt_data_source(cache, 5, symbol="SYM")
    assert source == "underlying"
    assert data == [futures_bar]


def test_reset_of_one_sibling_preserves_shared_underlying_state() -> None:
    service = AMTService()
    cache = Mock()
    cache.has_underlying_data.return_value = True
    cache.get_underlying_data.return_value = [SimpleNamespace(time="futures")]
    cache.get_option_data.return_value = []

    service._select_amt_data_source(cache, 5, symbol="NIFTY CALL")
    service._select_amt_data_source(cache, 5, symbol="NIFTY PUT")
    service._underlying_state_cache["NIFTY"] = (1.0, "TRENDING")

    service.reset("NIFTY CALL")
    assert "NIFTY" in service._underlying_state_cache

    # An active sibling that has not pinned a source yet still belongs to the
    # same underlying session and must not lose shared state.
    service._source_by_symbol["NIFTY FUTURE-UNPINNED"] = "underlying"
    service.reset("NIFTY PUT")
    assert "NIFTY" in service._underlying_state_cache

    service.reset("NIFTY FUTURE-UNPINNED")
    assert "NIFTY" not in service._underlying_state_cache
