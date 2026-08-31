"""Unit tests for gameloop worker functions (Lane C2 offload)."""

import pytest
from app.api.websocket.gameloop import (
    _build_initial_snapshots,
    _collect_symbol_deltas,
    _compute_delta,
)


class MockCoordinator:
    def __init__(self, data):
        self._data = data

    def symbols(self):
        return list(self._data.keys())

    def snapshot(self, symbol):
        return self._data.get(symbol, {})


def test_build_initial_snapshots():
    data = {
        "CRUDEOIL": {"_symbol": "CRUDEOIL", "ltp": 6200.0, "pnl": 150.0},
        "NATURALGAS": {"_symbol": "NATURALGAS", "ltp": 210.0, "pnl": 0.0},
    }
    coord = MockCoordinator(data)
    payloads, states = _build_initial_snapshots(coord, ["CRUDEOIL", "NATURALGAS"])

    assert len(payloads) == 2
    assert payloads[0]["_type"] == "full"
    assert payloads[0]["_symbol"] == "CRUDEOIL"
    assert payloads[0]["ltp"] == 6200.0
    assert "CRUDEOIL" in states
    assert "NATURALGAS" in states


def test_collect_symbol_deltas_only_changed():
    data = {
        "CRUDEOIL": {"_symbol": "CRUDEOIL", "ltp": 6200.0, "pnl": 150.0},
        "NATURALGAS": {"_symbol": "NATURALGAS", "ltp": 210.0, "pnl": 0.0},
    }
    coord = MockCoordinator(data)
    _, initial_states = _build_initial_snapshots(coord, ["CRUDEOIL", "NATURALGAS"])

    # No change
    deltas, next_states = _collect_symbol_deltas(coord, ["CRUDEOIL", "NATURALGAS"], initial_states)
    assert len(deltas) == 0

    # Mutate CRUDEOIL ltp
    data["CRUDEOIL"] = {"_symbol": "CRUDEOIL", "ltp": 6210.0, "pnl": 150.0}
    deltas, next_states = _collect_symbol_deltas(coord, ["CRUDEOIL", "NATURALGAS"], next_states)
    assert len(deltas) == 1
    assert deltas[0]["_symbol"] == "CRUDEOIL"
    assert deltas[0]["ltp"] == 6210.0
    assert "pnl" not in deltas[0]  # PnL was unchanged
    assert next_states["CRUDEOIL"]["ltp"] == 6210.0
