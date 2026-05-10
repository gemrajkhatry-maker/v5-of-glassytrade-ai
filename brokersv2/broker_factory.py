"""Broker Factory - Automatic broker initialization.

Creates broker instances automatically using credentials from .env.
Follows the same pattern as brokers/ infrastructure.

Usage:
    from brokersv2.broker_factory import get_broker
    
    # Automatically uses DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN from .env
    broker = get_broker()
    
    # Use broker (same API as brokers/)
    df = broker.historical("CRUDEOIL", "2026-04-01", "2026-05-08", "5m")
    chain = broker.option_chain("NIFTY")
    quote = broker.quote("GOLDM")
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Add brokers/ directory to Python path
project_root = Path(__file__).resolve().parent.parent
brokers_path = project_root / "brokers"
shared_path = project_root / "shared"
for path in [str(brokers_path), str(shared_path)]:
    if path not in sys.path:
        sys.path.insert(0, path)


def get_broker(broker_type: str = "dhan"):
    """
    Get broker instance with automatic credential loading.
    
    Uses the same pattern as brokers.broker.dhan.application.DhanConfig.from_env()
    
    Args:
        broker_type: Broker type ("dhan" is default)
    
    Returns:
        Broker instance ready to use (DhanFacade)
    
    Raises:
        ValueError: If credentials not found
        ImportError: If broker module not available
    """
    if broker_type == "dhan":
        return _get_dhan_broker()
    else:
        raise ValueError(f"Unknown broker type: {broker_type}")


def _get_dhan_broker():
    """
    Create Dhan broker with automatic credential loading.
    
    Uses DhanConfig.from_env() which auto-loads .env file
    (same as brokers/ infrastructure).
    """
    try:
        # Import brokers/ infrastructure
        from broker.dhan.application import DhanConfig, DhanFacade
        
        # Create config from environment (auto-loads .env)
        config = DhanConfig.from_env()
        
        # Create broker facade with config
        return DhanFacade(
            client_id=config.client_id,
            access_token=config.access_token
        )
        
    except ValueError as e:
        raise ValueError(
            f"Dhan credentials not configured: {e}\n"
            f"Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env file"
        )
    except ImportError as e:
        raise ImportError(
            f"Dhan broker module not found: {e}\n"
            f"Make sure 'brokers/' directory is in Python path"
        )


def get_broker_safe() -> Optional[object]:
    """
    Get broker instance safely (returns None on failure).
    
    Returns:
        Broker instance (DhanFacade) or None if credentials/modules missing
    """
    try:
        return get_broker()
    except (ValueError, ImportError):
        return None


# Convenience exports
__all__ = ["get_broker", "get_broker_safe"]
