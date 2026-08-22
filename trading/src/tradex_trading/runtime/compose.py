"""Shared session composition — the single assembly point for every boot path.

``runtime.startup.boot``, ``TradingSession.paper()`` and
``TradingSession.live()`` each build an :class:`ExecutionEngine` and wrap it in
a READY :class:`TradingSession`. This module is the one place that does the
session assembly so the two correctness-critical invariants can't drift
between paths:

- the session **always** shares the engine's OMS cache (fills/positions land
  where ``session.portfolio`` and the HTTP API read them — a second cache
  would silently show empty positions/orders), and
- the session is returned READY (``start()`` applied exactly once).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tradex_domain import BrokerId
from tradex_domain.protocols import BrokerAdapter
from tradex_domain.strategy import ScannerDefinition

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus
from tradex_trading.sdk.session import TradingSession


def compose(
    *,
    broker: BrokerAdapter,
    bus: ReactiveBus | ThreadSafeReactiveBus,
    engine: ExecutionEngine,
    broker_id: BrokerId,
    mode: str = "paper",
    scanner_engine: Any = None,
    scanner_definitions: Sequence[ScannerDefinition] | None = None,
    strategy_engine: Any = None,
    stream_backend: Any = None,
    backtest_loader: Any = None,
    fill_bridge: Any = None,
    live_orders_enabled: bool = True,
) -> TradingSession:
    """Assemble a READY :class:`TradingSession` from already-built components.

    The caller remains responsible for mode-specific wiring (broker, bus, fill
    source, stream backend, fill bridge, scanner/strategy engines); this
    function owns the session assembly that all paths share.
    """
    session = TradingSession(
        broker=broker,
        bus=bus,
        engine=engine,
        # Invariant: the session shares the engine's OMS cache.
        cache=engine.cache,
        broker_id=broker_id,
        mode=mode,
        scanner_engine=scanner_engine,
        scanner_definitions=scanner_definitions,
        strategy_engine=strategy_engine,
        stream_backend=stream_backend,
        backtest_loader=backtest_loader,
        fill_bridge=fill_bridge,
        live_orders_enabled=live_orders_enabled,
    )
    session.start()
    # Eagerly attach the orderflow analytics service so production sessions
    # accumulate footprint/delta/volume-profile/orderbook state from the live
    # quote/depth streams even when the HTTP API is never opened.
    session.orderflow
    return session


__all__ = ["compose"]
