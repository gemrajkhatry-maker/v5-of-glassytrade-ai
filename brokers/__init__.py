"""
Brokers - Multi-broker abstraction with clean architecture.

Provides:
- IBrokerPort: Abstract interface for broker implementations
- PaperBroker: Simulated broker for testing
- DhanBroker: Production Dhan broker (self-contained, no dhanhq_custom dependency)
- BrokerGateway: Unified API with factory pattern and circuit breaker

Usage:
    # Paper trading (testing)
    from brokers import BrokerGateway
    gateway = BrokerGateway.paper()
    quote = gateway.get_quote("RELIANCE")

    # Dhan broker (production) — credentials auto-loaded from .env
    gateway = BrokerGateway.dhan()
    quote = gateway.get_quote("RELIANCE")
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

# Infrastructure Layer
from brokers.broker.paper import PaperBroker
from brokers.broker.dhan import DhanBroker

# Application Layer
from brokers.gateway import (
    BrokerType,
    BrokerFactory,
    CircuitBreaker,
    CircuitState,
    CircuitBreakerError,
    BrokerGateway,
    create_paper_gateway,
    create_dhan_gateway,
)

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
    'PaperBroker',
    'DhanBroker',
    
    # Gateway
    'BrokerType',
    'BrokerFactory',
    'CircuitBreaker',
    'CircuitState',
    'CircuitBreakerError',
    'BrokerGateway',
    'create_paper_gateway',
    'create_dhan_gateway',
    
    # Reactive (lazy import to avoid rx dependency)
    # Use: from brokers.reactive import ReactiveBroker
]
