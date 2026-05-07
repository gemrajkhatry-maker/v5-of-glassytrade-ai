"""Test configuration for pytest."""
import sys
from pathlib import Path

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
    """Register live marker."""
    config.addinivalue_line(
        "markers",
        "live: live market tests (requires Dhan credentials and --live option)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip live tests unless --live option is provided."""
    if config.getoption("--live"):
        return
    
    skip_live = pytest.mark.skip(reason="need --live option to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


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