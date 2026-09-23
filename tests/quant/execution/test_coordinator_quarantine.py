"""Tests for coordinator wiring of paper position quarantine (Phase 0.6).

Verifies that QuantCoordinator.start() runs PaperPositionReconciler and
exposes quarantined positions via quarantined_positions().
"""
from unittest.mock import MagicMock, patch



class FakeStorage:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._deleted = []

    def load_open_positions(self):
        return list(self._rows)

    def delete_open_position(self, pos_id):
        self._deleted.append(pos_id)


def _row(symbol, qty=1, open_price=100.0):
    return {
        "symbol": symbol,
        "quantity": qty,
        "open_price": open_price,
        "side": "BUY",
        "open_time": "2026-09-07T09:15:00+05:30",
    }


def test_coordinator_has_quarantined_positions_method():
    """QuantCoordinator must expose quarantined_positions()."""
    from quant.multi_engine import QuantCoordinator
    assert hasattr(QuantCoordinator, "quarantined_positions")


def test_coordinator_start_runs_reconciliation():
    """start() must run PaperPositionReconciler with the scanned symbols."""
    from quant.multi_engine import QuantCoordinator

    # Build a minimal coordinator mock
    coord = MagicMock(spec=QuantCoordinator)
    coord.config = {"live_oms_enabled": False}
    coord._storage = FakeStorage([_row("NIFTY 1 SEP 24050 CALL")])
    coord._scan = MagicMock(return_value=["NIFTY 1 SEP 24200 CALL"])
    coord._refresh_gex = MagicMock()
    coord._feed = MagicMock()
    coord._spawn_engine = MagicMock(return_value=MagicMock())
    coord._start_eod_watchdog = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._lock = MagicMock()
    coord._engines = {}
    coord.started = False

    # Patch is_trading_day to True
    with patch("quant.multi_engine.is_trading_day", return_value=True):
        # Call the real start() on our mock
        QuantCoordinator.start(coord)

    # Reconciliation should have been run with the active universe
    coord._spawn_engine.assert_called_once()
    # The reconciler should classify NIFTY 1 SEP 24050 CALL as stale
    assert hasattr(coord, "_quarantined")
    assert "NIFTY 1 SEP 24050 CALL" in coord._quarantined


def test_coordinator_quarantined_positions_returns_symbols():
    """quarantined_positions() returns the set of quarantined symbols."""
    from quant.multi_engine import QuantCoordinator

    coord = MagicMock(spec=QuantCoordinator)
    coord._quarantined = {"NIFTY 1 SEP 24050 CALL", "MIDCPNIFTY 29 SEP 14700 PUT"}

    result = QuantCoordinator.quarantined_positions(coord)
    assert result == {"NIFTY 1 SEP 24050 CALL", "MIDCPNIFTY 29 SEP 14700 PUT"}


def test_coordinator_quarantined_positions_empty_by_default():
    """quarantined_positions() returns empty set when no quarantine has run."""
    from quant.multi_engine import QuantCoordinator

    coord = MagicMock(spec=QuantCoordinator)
    coord._quarantined = set()

    result = QuantCoordinator.quarantined_positions(coord)
    assert result == set()


def test_coordinator_start_passes_open_positions_to_spawn():
    """start() must pass only OPEN positions to _spawn_engine(), not quarantined."""
    from quant.multi_engine import QuantCoordinator

    storage = FakeStorage([
        _row("NIFTY 1 SEP 24200 CALL"),  # active
        _row("NIFTY 1 SEP 24050 CALL"),  # stale
    ])

    coord = MagicMock(spec=QuantCoordinator)
    coord.config = {"live_oms_enabled": False}
    coord._storage = storage
    coord._scan = MagicMock(return_value=["NIFTY 1 SEP 24200 CALL"])
    coord._refresh_gex = MagicMock()
    coord._feed = MagicMock()
    coord._spawn_engine = MagicMock(return_value=MagicMock())
    coord._start_eod_watchdog = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._lock = MagicMock()
    coord._engines = {}
    coord.started = False

    with patch("quant.multi_engine.is_trading_day", return_value=True):
        QuantCoordinator.start(coord)

    # _spawn_engine should be called with the open position row, not the stale one
    # The reconciler result should be stored
    assert hasattr(coord, "_reconciliation_result")
    result = coord._reconciliation_result
    assert len(result.open_positions) == 1
    assert result.open_positions[0]["symbol"] == "NIFTY 1 SEP 24200 CALL"
    assert len(result.quarantined) == 1
    assert result.quarantined[0].symbol == "NIFTY 1 SEP 24050 CALL"
