"""Test configuration for pytest."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

# Add backendv2 to path
backendv2_path = Path(__file__).parent.parent
sys.path.insert(0, str(backendv2_path))


def pytest_addoption(parser):
    """Add --live option for live market tests."""
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live market tests (requires Dhan credentials)"
    )


def pytest_configure(config):
    """Register markers."""
    config.addinivalue_line(
        "markers",
        "live: live market tests (requires Dhan credentials and --live option)"
    )
    config.addinivalue_line(
        "markers",
        "slow: long-running tests"
    )


def pytest_collection_modifyitems(config, items):
    """Skip live tests unless --live option is provided."""
    if config.getoption("--live"):
        return
    
    skip_live = pytest.mark.skip(reason="need --live option to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


# ============================================================
# Shared Fixtures
# ============================================================

@pytest.fixture(scope="session")
def dhan_credentials():
    """Check if Dhan credentials are available."""
    import os
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        pytest.skip("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN must be set")
    
    return {
        "client_id": client_id,
        "access_token": access_token,
    }


@pytest.fixture
def mock_trading_session():
    """Create a mock TradingSession for testing."""
    session = MagicMock()
    session.is_active = True
    session.get_state.return_value = {
        "symbol": "NIFTY",
        "tick_count": 0,
        "positions": [],
        "amt_state": "BALANCED",
    }
    return session


@pytest.fixture
def mock_orchestrator():
    """Create a mock Orchestrator for testing."""
    orchestrator = MagicMock()
    orchestrator.get_state.return_value = {
        "status": "running",
        "sessions": {},
    }
    return orchestrator


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus for testing."""
    bus = MagicMock()
    bus.publish = MagicMock()
    bus.subscribe = MagicMock()
    bus.unsubscribe = MagicMock()
    bus.get_history = MagicMock(return_value=[])
    return bus


@pytest.fixture
def mock_storage():
    """Create a mock storage adapter for testing."""
    storage = MagicMock()
    storage.save = AsyncMock()
    storage.load = AsyncMock(return_value=None)
    storage.save_position = AsyncMock()
    storage.load_positions = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def mock_broker():
    """Create a mock broker adapter for testing."""
    broker = MagicMock()
    broker.submit_order = AsyncMock(return_value={"order_id": "test-123", "status": "filled"})
    broker.cancel_order = AsyncMock(return_value={"status": "cancelled"})
    broker.get_positions = AsyncMock(return_value=[])
    broker.get_orders = AsyncMock(return_value=[])
    return broker
