"""Integration tests for SessionStateManager wiring to FastAPI.

These tests verify that SessionStateManager is properly instantiated
during app lifespan and can process ticks for WebSocket streaming.

TDD Status: RED→GREEN cycle in progress
"""
import pytest
from fastapi.testclient import TestClient
from app.api.main import app
from app.application.service.session_state_manager import SessionStateManager


class TestSessionManagerLifecycle:
    """Test SessionStateManager is properly wired during app startup."""
    
    def test_session_service_registered_in_lifespan(self):
        """SessionStateManager is created and accessible via app.state.
        
        Behavior: When FastAPI app starts, SessionStateManager should be
        instantiated and registered to app.state.session_service.
        
        This is critical for WebSocket gameloop to process ticks.
        """
        with TestClient(app) as client:
            # Verify session_service exists
            assert hasattr(app.state, 'session_service'), \
                "app.state.session_service not set in lifespan"
            assert app.state.session_service is not None
            assert isinstance(app.state.session_service, SessionStateManager), \
                f"Expected SessionStateManager, got {type(app.state.session_service)}"
    
    def test_process_tick_creates_session(self):
        """Processing a tick creates session and returns state.
        
        Behavior: When process_tick() is called with a symbol and tick data,
        it should:
        1. Create a new session if one doesn't exist
        2. Append tick to session data
        3. Return the session state
        
        This enables client-driven WebSocket mode to work.
        """
        from app.domain.trading.model.value_objects import OHLC
        
        with TestClient(app) as client:
            session_service = app.state.session_service
            
            # Create test tick
            tick = OHLC(
                time="2026-05-06T09:15:00",
                open=7250.0, high=7255.0, low=7248.0, close=7253.0,
                volume=100.0, vwap=7252.0, taker_buy_volume=60.0, delta=20.0
            )
            
            # Process tick
            state = session_service.process_tick("CRUDEOIL", tick, None)
            
            # Verify session created
            assert state is not None, "process_tick returned None"
            assert state.symbol == "CRUDEOIL"
            assert len(state.data) == 1
            assert state.data[0].close == 7253.0
    
    def test_process_tick_accumulates_data(self):
        """Multiple ticks accumulate in session data.
        
        Behavior: Subsequent ticks for same symbol should append to
        existing session, not create new sessions.
        """
        from app.domain.trading.model.value_objects import OHLC
        
        with TestClient(app) as client:
            session_service = app.state.session_service
            
            # Process 3 ticks
            for i in range(3):
                tick = OHLC(
                    time=f"2026-05-06T09:{15+i}:00",
                    open=7250.0 + i, high=7255.0 + i,
                    low=7248.0 + i, close=7253.0 + i,
                    volume=100.0, vwap=7252.0 + i,
                    taker_buy_volume=60.0, delta=20.0
                )
                session_service.process_tick("CRUDEOIL", tick, None)
            
            # Verify all accumulated
            session = session_service.get_or_create_session("CRUDEOIL")
            assert len(session.data) == 3, f"Expected 3 ticks, got {len(session.data)}"
    
    def test_multiple_symbols_isolated(self):
        """Sessions for different symbols are isolated.
        
        Behavior: Ticks for CRUDEOIL should not appear in NATURALGAS session.
        """
        from app.domain.trading.model.value_objects import OHLC
        
        with TestClient(app) as client:
            session_service = app.state.session_service
            
            # Process tick for CRUDEOIL
            tick1 = OHLC(
                time="2026-05-06T09:15:00",
                open=7250.0, high=7255.0, low=7248.0, close=7253.0,
                volume=100.0, vwap=7252.0, taker_buy_volume=60.0, delta=20.0
            )
            session_service.process_tick("CRUDEOIL", tick1, None)
            
            # Process tick for NATURALGAS
            tick2 = OHLC(
                time="2026-05-06T09:15:00",
                open=285.0, high=287.0, low=284.0, close=286.0,
                volume=50.0, vwap=285.5, taker_buy_volume=30.0, delta=10.0
            )
            session_service.process_tick("NATURALGAS", tick2, None)
            
            # Verify isolation
            crude_session = session_service.get_or_create_session("CRUDEOIL")
            gas_session = session_service.get_or_create_session("NATURALGAS")
            
            assert len(crude_session.data) == 1
            assert len(gas_session.data) == 1
            assert crude_session.data[0].close == 7253.0
            assert gas_session.data[0].close == 286.0
