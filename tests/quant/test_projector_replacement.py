"""TDD tests for StateProjector replacement with EventStore.fold()."""

import pytest

from quant.event_store import EventStore
from quant.events import BarClosed, PositionOpened
from quant.state import project_state
from quant.state_machine import Bar as StateBar, PositionState
from quant.ws_adapter import view_state_to_ws


class TestProjectorReplacement:
    def test_project_state_matches_events(self):
        """project_state() should match event store fold."""
        store = EventStore()
        store.append(
            BarClosed(
                symbol="NIFTY",
                time="t0",
                bar=StateBar(close=100.0),
            )
        )
        state = store.fold()
        view_state = project_state(state)
        assert view_state.ltp == 100.0

    def test_ws_adapter_uses_event_store(self):
        """WS adapter should use EventStore.fold()."""
        store = EventStore()
        pos = PositionState(id="abc", entry=100, size=100, sl=95, tp=110, side="LONG")
        store.append(PositionOpened(symbol="NIFTY", time="t0", position=pos))
        state = store.fold()
        ws_snapshot = view_state_to_ws(state)
        assert ws_snapshot["_symbol"] == "NIFTY"
        assert len(ws_snapshot["portfolio"]["positions"]) == 1

    def test_projector_deprecated(self):
        """StateProjector should be deprecated."""
        with pytest.warns(DeprecationWarning):
            from quant.state import StateProjector

            projector = StateProjector()
