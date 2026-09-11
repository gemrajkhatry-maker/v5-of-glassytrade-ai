"""Implementation of IMarketDataPort for DhanHQ (backend/app/infrastructure/adapters/dhan_market_data.py).

Alias/bridge for dhan_adapter.py to satisfy target v6.0 layout.
"""

from __future__ import annotations

from backend.app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter

__all__ = [
    "DhanMarketDataAdapter",
]
