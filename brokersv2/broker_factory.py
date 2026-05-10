"""
Broker Factory — DEPRECATED.

This module is kept for backward compatibility only.
Use brokersv2.app.bootstrap instead:

    # For CLI / async use (high-level string-based API):
    from brokersv2.app.bootstrap import create_dhan_gateway
    gateway = create_dhan_gateway()

    # For adapters / OMS (protocol-based, IBrokerAdapter):
    from brokersv2.app.bootstrap import create_dhan_adapter
    adapter = create_dhan_adapter()

The legacy get_broker() function still works but requires the external
brokers/ directory to be present on the file system next to this project,
mutates sys.path, and will be removed in a future release.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from typing import Optional

warnings.warn(
    "brokersv2.broker_factory is deprecated. "
    "Import from brokersv2.app.bootstrap instead: "
    "create_dhan_gateway() or create_dhan_adapter().",
    DeprecationWarning,
    stacklevel=2,
)

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
