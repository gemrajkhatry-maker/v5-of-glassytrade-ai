"""
Brokers - Multi-broker abstraction with clean architecture.

Provides:
- IBrokerPort: Abstract interface for broker implementations
- DhanBroker: Production Dhan broker (self-contained, no dhanhq_custom dependency)

The legacy ``BrokerGateway`` facade (brokers/gateway.py) was removed; the
active paths are the Dhan hexagon (``brokers.broker.dhan``, used by the
backend adapters) and the quant ``LiveGateway`` (``quant/brokers``).
"""

# Auto-load .env from project root so credentials are available without
# the caller having to call load_dotenv() themselves.
import pathlib as _pathlib

try:
    from dotenv import load_dotenv as _load_dotenv
    _env_file = _pathlib.Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        _load_dotenv(_env_file, override=False)  # override=False: real env vars take precedence
except ImportError:
    pass  # python-dotenv not installed; rely on env vars being set externally

# Domain Layer
from brokers.broker.types import (
    Exchange,
    OptionType,
    OrderSide,
    OrderType,
    OrderStatus,
)
from brokers.broker.entities import (
    Instrument,
    Quote,
    Tick,
    Order,
    Position,
    OptionChain,
)
from brokers.broker.ports import IBrokerPort

# DhanBroker is imported lazily to avoid circular imports during
# partial module initialization when sub-modules import back into this package.
def __getattr__(name):
    if name == "DhanBroker":
        from brokers.broker.dhan import DhanBroker
        return DhanBroker
    raise AttributeError(f"module 'brokers' has no attribute {name!r}")

__all__ = [
    # Types
    'Exchange',
    'OptionType',
    'OrderSide',
    'OrderType',
    'OrderStatus',
    
    # Entities
    'Instrument',
    'Quote',
    'Tick',
    'Order',
    'Position',
    'OptionChain',
    
    # Port
    'IBrokerPort',
    
    # Brokers
    'DhanBroker',
]
