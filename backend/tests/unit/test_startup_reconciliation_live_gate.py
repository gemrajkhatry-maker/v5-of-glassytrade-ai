"""Live-mode gate for startup reconciliation.

In live mode (GLASSYTRADE_ENV=live) a failed reconciliation must block
startup — booting with unknown broker state is not acceptable with real
money. In paper mode the existing advisory path is preserved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _patch_reconcile_to_raise(monkeypatch):
    """Patch StartupReconciliation.reconcile to raise."""
    from app.domain.ops.startup_reconciliation import StartupReconciliation

    def _boom(self):
        raise ConnectionError("broker unreachable in test")

    monkeypatch.setattr(StartupReconciliation, "reconcile", _boom)


def _patch_live_broker_off_network(monkeypatch):
    """The reconciliation gate — not Dhan auth — is the thing under test.

    Boot resolves the broker adapter BEFORE the gate runs, so a stale/expired
    DHAN_ACCESS_TOKEN in the environment would otherwise fail the test with
    DhanAuthError before reconciliation is ever reached. Stub the broker
    construction so the test's verdict depends only on the gate.
    """
    from unittest.mock import MagicMock

    from app.infrastructure.adapters.dhan_broker_adapter import DhanBrokerAdapter

    monkeypatch.setattr(
        DhanBrokerAdapter,
        "_create_broker",
        lambda self: MagicMock(name="DhanBroker"),
        raising=True,
    )


def _build_app_with_failing_reconciliation(monkeypatch):
    """Create the app with StartupReconciliation.reconcile patched to raise."""
    from app.main import create_application

    _patch_reconcile_to_raise(monkeypatch)
    return create_application()


def test_live_mode_refuses_boot_on_reconciliation_failure(monkeypatch):
    """GLASSYTRADE_ENV=live + reconcile failure → startup raises RuntimeError."""
    from app.main import create_application

    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("TRADING_MODE", "live")
    _patch_reconcile_to_raise(monkeypatch)
    _patch_live_broker_off_network(monkeypatch)

    with pytest.raises(RuntimeError, match="Startup reconciliation failed in live mode"):
        create_application()


def test_paper_mode_continues_past_reconciliation_failure(monkeypatch):
    """GLASSYTRADE_ENV=paper (or unset) + reconcile failure → startup continues."""
    monkeypatch.delenv("GLASSYTRADE_ENV", raising=False)
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    app = _build_app_with_failing_reconciliation(monkeypatch)

    # NB: intentionally NOT used as a context manager — the lifespan shutdown
    # closes the app's shared storage singleton, poisoning later tests in the
    # same process ("Cannot operate on a closed database"). The endpoint under
    # test only needs the module-level app state, not the lifespan.
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
