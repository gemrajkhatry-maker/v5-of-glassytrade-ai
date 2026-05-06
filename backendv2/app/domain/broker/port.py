"""Backward-compatible shim for legacy import paths.

The active broker contract is ``app.domain.shared.port.broker.IBroker``.
This module is retained only for imports that still target the legacy
``app.domain.broker.port`` path.
"""

import warnings

from app.domain.shared.port.broker import IBroker


BrokerPort = IBroker

warnings.warn(
    "app.domain.broker.port is deprecated. "
    "Import IBroker from app.domain.shared.port.broker instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["BrokerPort", "IBroker"]