import pytest
import threading
import time
from unittest.mock import MagicMock, patch
from app.application.handlers.llm_entry_handler import LLMEntryHandler
from app.domain.trading.models.value_objects import OHLC, AMTResult
from app.domain.trading.models.aggregates import Portfolio

class FakeOHLC:
    def __init__(self, price=100.0):
        self.time = "2026-03-17T14:40:59.474373+00:00"
        self.open = price
        self.high = price + 1.0
        self.low = price - 1.0
        self.close = price
        self.volume = 100.0
        self.delta = 10.0
        self.vwap = price

class FakeAMTResult:
    def __init__(self):
        self.market_state = "BALANCED"
        self.poc = 100.0
        self.value_area_high = 105.0
        self.value_area_low = 95.0
        self.lvns = []
        self.hvns = []
        self.aggression = 0.5
        self.session_vwap = 100.0
        self.aggressive_prints = []
        self.cvd_slope = 0.0
        self.cvd_divergence = ""
        self.profile_shape = "D"
        self.vwap_upper_2 = 0.0
        self.vwap_lower_2 = 0.0
        self.price_velocity = 0.0
        self.market_structure = "NORMAL"
        self.lvn_play = None
        self.dev_poc = 0.0
        self.dev_vah = 0.0
        self.dev_val = 0.0
        self.leg_poc = 0.0
        self.leg_vah = 0.0
        self.leg_val = 0.0
        self.leg_lvns = []
        self.signal = None
        self.structure_confidence = 0.0
        self.cvd_delta = 0.0
    
    def __getattr__(self, name):
        return 0.0

@patch("app.application.handlers.llm_entry_handler.get_session_info")
@patch("app.application.handlers.llm_entry_handler.three_align_check", return_value=(True, True, False))
@patch("app.application.handlers.llm_entry_handler.build_entry_signal", return_value=None)
@patch("app.config.settings.LLM_EXECUTION_ENABLED", True)
@patch("app.config.settings.ALLOW_SHORT", True)
def test_fix_none_entry_signal_lock(mock_build_sig, mock_gate, mock_si):
    # Mocking dependencies
    gen_ai = MagicMock()
    gen_ai.is_ready.return_value = True
    gen_ai.analyze_market.return_value = {
        "direction": "LONG",
        "rationale": "test rationale",
        "confidence": "High",
        "raw_output": "LONG",
        "input_prompt": "test",
        "market_state": "Balanced",
        "aggression": "0.50",
    }
    
    event_bus = MagicMock()
    storage = MagicMock()
    trade_manager = MagicMock()
    journal = MagicMock()
    
    handler = LLMEntryHandler(
        gen_ai_service=gen_ai,
        event_bus=event_bus,
        storage=storage,
        trade_manager=trade_manager,
        journal=journal,
    )

    # Setup session
    session = MagicMock()
    session.symbol = "NIFTY"
    session._lock = threading.Lock()
    session._ai_running = True
    session.data = [FakeOHLC() for _ in range(20)]
    session.portfolio = MagicMock(spec=Portfolio)
    session.portfolio.positions = []
    session._session_risk_manager = MagicMock()
    session._session_risk_manager.can_trade = True
    
    tick = FakeOHLC()
    amt = FakeAMTResult()
    
    # Run the worker loop logic (by manually putting item in queue and waiting)
    handler.run_entry(session, "NIFTY", tick, amt)
    
    # Wait for the worker queue to drain
    q = handler._llm_queues.get("NIFTY")
    if q:
        q.join()
    
    # Verify that session._ai_running has been reset to False
    assert session._ai_running is False
    
    # Cleanup
    handler.cleanup()
