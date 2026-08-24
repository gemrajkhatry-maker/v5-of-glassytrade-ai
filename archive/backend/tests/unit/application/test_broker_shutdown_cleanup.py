from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock


def test_shutdown_transport_helper_closes_both_resources_in_order():
    """Both live transport adapters must be closed through the app boundary."""
    from app.main import close_runtime_transports

    order: list[str] = []
    app = SimpleNamespace(
        state=SimpleNamespace(
            market_data=SimpleNamespace(
                close_sync=Mock(side_effect=lambda: order.append("market-data-close"))
            ),
            broker=SimpleNamespace(
                close_sync=Mock(side_effect=lambda: order.append("broker-close"))
            ),
        )
    )

    close_runtime_transports(app)

    assert order == ["market-data-close", "broker-close"]
