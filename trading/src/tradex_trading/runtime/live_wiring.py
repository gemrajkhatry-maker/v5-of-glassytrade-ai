"""Shared live-path wiring — one construction for both live boot entry points.

``runtime.startup.boot`` (fail-closed: any wiring failure aborts boot) and
``TradingSession.live`` (best-effort SDK convenience: failures degrade to no
stream/fill bridge) build the same two objects: the broker order-stream backend
and the live fill bridge that translates broker order updates into
``OrderFilled`` events on the bus. This module owns that construction so the
two paths cannot drift; the ``fail_closed`` flag selects the safety posture.
"""

from __future__ import annotations

import logging
from typing import Any

from tradex_domain.protocols import BrokerAdapter

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus

log = logging.getLogger(__name__)


def build_live_streaming(
    *,
    broker: BrokerAdapter,
    bus: ReactiveBus | ThreadSafeReactiveBus,
    engine: ExecutionEngine,
    fail_closed: bool = True,
) -> tuple[Any | None, Any | None]:
    """Build the ``(stream_backend, fill_bridge)`` pair for a live broker.

    The order-stream backend exposes ``subscribe_orders`` so
    ``session.stream.subscribe_orders/positions`` reaches the broker WebSocket;
    the fill bridge translates those order updates into bus ``OrderFilled``
    events so live fills reach the OMS. Live delta fills are stamped with the
    broker's exchange trade ids (``TradeBookFillIdResolver``) when the broker
    exposes a REST trade book, so equal-lot partials dedup exactly instead of
    under-counting; brokers without one fall back to the composite fingerprint.

    Returns
    -------
    ``(stream_backend, fill_bridge)``.
    ``(None, None)`` when the broker exposes no usable order-stream backend and
    ``fail_closed`` is False. When ``fail_closed`` is True any failure raises
    ``ValueError`` with a descriptive message (boot must never trade blind).
    """
    sb = getattr(broker, "stream_backend", None)
    if not callable(sb):
        if fail_closed:
            raise ValueError(
                "live mode requires a broker order-stream backend; "
                f"{type(broker).__name__} exposes no stream_backend"
            )
        return None, None
    try:
        stream_backend = sb()
    except Exception as exc:
        if fail_closed:
            raise ValueError(
                f"live mode order-stream backend failed to build: {exc}"
            ) from exc
        return None, None
    if not hasattr(stream_backend, "subscribe_orders"):
        if fail_closed:
            raise ValueError(
                "live mode requires an order stream with subscribe_orders"
            )
        return None, None

    # Live fill bridge: translate broker order-stream updates into bus
    # OrderFilled events so live fills reach the OMS (HIGH-4).
    try:
        from tradex_trading.sdk.live_fill_bridge import (
            LiveFillBridge,
            TradeBookFillIdResolver,
        )

        # Stamp live delta fills with the broker's exchange trade ids
        # (Dhan ``tradeId`` from GET /trades) so equal-lot partials dedup
        # exactly instead of under-counting (parity review area #10 —
        # duplicate-event safety). Brokers without a REST trade book fall
        # back to the composite fingerprint.
        trade_book = getattr(broker, "trade_book", None)
        resolver = (
            TradeBookFillIdResolver(trade_book)
            if callable(trade_book) else None
        )
        fill_bridge = LiveFillBridge(
            bus, engine, stream_backend.subscribe_orders,
            trade_id_resolver=resolver,
            unsubscribe_orders=stream_backend.unsubscribe,
        )
    except ValueError:
        raise
    except Exception as exc:
        if fail_closed:
            raise ValueError(
                f"live mode fill bridge failed to build: {exc}"
            ) from exc
        log.warning("live fill bridge unavailable", exc_info=True)
        return None, None
    return stream_backend, fill_bridge


__all__ = ["build_live_streaming"]
